"""Interactive mailbox poller for locally approved, allowlisted agent operations.

The prototype supports fixed diagnostics, reviewed patches, structured story-plan
storage/compilation, local asset indexing, and one deterministic Blender preview.
It does not execute arbitrary remote commands or claim full animation support.
Service start/stop/backup operations are not implemented.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any

from local_agent.cli import doctor, preflight, run_tests, status, tail_logs
from local_agent.github_queue import GitHubQueueClient, QueueConfig, QueueTransportError
from local_agent.control_protocol import REMOTE_APPROVABLE_OPERATIONS
from local_agent.reporting import _redact_value, write_report
from local_agent.error_knowledge import diagnose_error
from local_agent.notifications import notify_user
from local_agent.result_outbox import ResultOutbox

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / ".local_agent" / "poller_state.json"


def _ensure_agent_dir() -> Path:
    """Create the private state directory only if it remains inside the source root."""
    candidate = ROOT / ".local_agent"
    if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
        raise RuntimeError("Local agent state directory must not be a symlink or junction")
    candidate.mkdir(parents=True, exist_ok=True)
    resolved = candidate.resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise RuntimeError("Local agent state directory resolves outside the source root")
    return resolved


def _result_outbox() -> ResultOutbox:
    return ResultOutbox(_ensure_agent_dir() / "pending_results")


def _publish_result_durable(client: GitHubQueueClient, task_id: str, result: dict[str, Any]) -> str:
    """Persist each result before publishing it; retain it if the network fails."""
    return _result_outbox().publish(client, task_id, result)
SUPPORTED_HANDLERS = {
    "doctor": doctor,
    "preflight": preflight,
    "status": status,
    "logs": tail_logs,
    "test": run_tests,
}


def _apply_patch(patch: str, task_id: str) -> dict[str, Any]:
    """Apply and test a patch in an isolated Git worktree, never in the active checkout."""
    import re

    if not (ROOT / ".git").exists():
        return {"status": "blocked", "reason": "project_root_is_not_a_git_checkout"}
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "-", task_id)[:80]
    if not safe_id:
        return {"status": "blocked", "reason": "invalid_task_id_for_isolated_worktree"}

    branch = f"agent/task-{safe_id}"
    worktree_root = ROOT.parent / ".local_agent_worktrees"
    worktree = worktree_root / f"task-{safe_id}"
    if worktree.exists():
        return {
            "status": "blocked",
            "reason": "task_worktree_already_exists; inspect it before retrying",
            "worktree": str(worktree),
            "branch": branch,
        }

    def run_git(args: list[str], *, cwd: Path = ROOT, timeout: int = 60, input_text: str | None = None):
        return subprocess.run(
            ["git", *args], cwd=cwd, input=input_text, capture_output=True,
            text=True, timeout=timeout, check=False, shell=False,
        )

    try:
        head = run_git(["rev-parse", "--verify", "HEAD"])
        if head.returncode != 0:
            return {"status": "blocked", "reason": "could_not_resolve_base_commit"}
        base_sha = head.stdout.strip()
        branch_check = run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"])
        if branch_check.returncode == 0:
            return {
                "status": "blocked",
                "reason": "task_branch_already_exists; inspect it before retrying",
                "branch": branch,
            }

        worktree_root.mkdir(parents=True, exist_ok=True)
        created = run_git(["worktree", "add", "-b", branch, str(worktree), base_sha], timeout=120)
        if created.returncode != 0:
            return {
                "status": "error",
                "reason": "could_not_create_isolated_worktree",
                "stderr_tail": [line[:500] for line in created.stderr.splitlines()[-20:]],
            }

        checked = run_git(["apply", "--check"], cwd=worktree, input_text=patch)
        if checked.returncode != 0:
            reason = "git_apply_check_failed"
            error_lines = [line[:500] for line in checked.stderr.splitlines()[-20:]]
            return _discard_failed_worktree(
                run_git, worktree, branch,
                {"status": "rejected", "reason": reason, "stderr_tail": error_lines},
            )

        applied = run_git(["apply"], cwd=worktree, input_text=patch)
        if applied.returncode != 0:
            error_lines = [line[:500] for line in applied.stderr.splitlines()[-20:]]
            return _discard_failed_worktree(
                run_git, worktree, branch,
                {"status": "failed_rolled_back", "reason": "git_apply_failed", "stderr_tail": error_lines},
            )

        try:
            tests = subprocess.run(
                [sys.executable, "-m", "pytest", "-q"],
                cwd=worktree, capture_output=True, text=True, timeout=900,
                check=False, shell=False,
            )
        except subprocess.TimeoutExpired:
            return _discard_failed_worktree(
                run_git, worktree, branch,
                {"status": "failed_rolled_back", "reason": "post_patch_tests_timed_out", "timeout_seconds": 900},
            )
        except OSError as exc:
            return _discard_failed_worktree(
                run_git, worktree, branch,
                {"status": "failed_rolled_back", "reason": "post_patch_tests_could_not_start", "error_type": type(exc).__name__},
            )

        if tests.returncode != 0:
            return _discard_failed_worktree(
                run_git, worktree, branch,
                {
                    "status": "failed_rolled_back",
                    "reason": "post_patch_tests_failed",
                    "test_return_code": tests.returncode,
                    "stdout_tail": [line[:1000] for line in tests.stdout.splitlines()[-60:]],
                    "stderr_tail": [line[:1000] for line in tests.stderr.splitlines()[-60:]],
                },
            )

        return {
            "status": "completed",
            "reason": "patch_applied_and_tests_passed_in_isolated_worktree",
            "base_commit": base_sha,
            "branch": branch,
            "worktree": str(worktree),
            "test_return_code": tests.returncode,
            "requires_review_before_merge": True,
            "active_checkout_modified": False,
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "git_operation_timed_out"}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}


def _discard_failed_worktree(run_git, worktree: Path, branch: str, result: dict[str, Any]) -> dict[str, Any]:
    """Remove only the disposable worktree created for this task after a failure."""
    remove = run_git(["worktree", "remove", "--force", str(worktree)], timeout=120)
    delete_branch = run_git(["branch", "-D", branch], timeout=60)
    if remove.returncode != 0 or delete_branch.returncode != 0:
        return {
            "status": "failed_needs_user",
            "reason": "failed_task_cleanup_not_fully_verified",
            "original_failure": result,
            "worktree_remove_return_code": remove.returncode,
            "branch_delete_return_code": delete_branch.returncode,
            "worktree": str(worktree),
            "branch": branch,
        }
    return {
        **result,
        "rollback_verified": True,
        "temporary_worktree_removed": True,
        "temporary_branch_removed": True,
    }


def _run_blender_forest_preview(arguments: dict[str, Any]) -> dict[str, Any]:
    """Run the single allowlisted Blender task using local-only configuration."""
    executable = os.environ.get("BLENDER_EXECUTABLE", "").strip()
    workspace = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not executable or not workspace:
        return {
            "status": "blocked",
            "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally",
            "remote_paths_or_commands_accepted": False,
        }
    from local_agent.blender_bridge import BlenderBridge, BlenderBridgeError
    try:
        bridge = BlenderBridge(executable, workspace)
        result = bridge.run_task(
            "forest_preview",
            project_name=arguments["project_name"],
            render=arguments.get("render", True),
            preview=arguments.get("preview", True),
            cycles=arguments.get("cycles", False),
        )
        return {"status": "completed", "task": "blender_forest_preview", "result": result}
    except BlenderBridgeError as exc:
        return {"status": "failed", "task": "blender_forest_preview", "reason": str(exc)[:1000]}


def _run_save_story_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    """Store a validated creative plan locally; do not launch Blender or execute plan text."""
    workspace = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not workspace:
        return {"status": "blocked", "reason": "set_LOCAL_AGENT_WORKSPACE_locally"}
    from local_agent.story_plan import StoryPlanError, save_story_plan
    try:
        return save_story_plan(workspace, arguments["story_plan"])
    except StoryPlanError as exc:
        return {"status": "rejected", "reason": str(exc)[:1000]}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}


def _run_scan_project_assets(arguments: dict[str, Any]) -> dict[str, Any]:
    """Index local asset filenames only; never load or upload asset content."""
    workspace = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not workspace:
        return {"status": "blocked", "reason": "set_LOCAL_AGENT_WORKSPACE_locally"}
    from local_agent.asset_registry import AssetRegistryError, scan_project_assets
    try:
        return scan_project_assets(workspace, arguments["project_name"])
    except AssetRegistryError as exc:
        return {"status": "rejected", "reason": str(exc)[:1000]}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}


def _run_compile_story_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    """Compile an existing local story plan into an inert storyboard manifest."""
    workspace = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not workspace:
        return {"status": "blocked", "reason": "set_LOCAL_AGENT_WORKSPACE_locally"}
    from local_agent.scene_compiler import StoryCompileError, compile_project_story
    try:
        return compile_project_story(workspace, arguments["project_name"])
    except StoryCompileError as exc:
        return {"status": "rejected", "reason": str(exc)[:1000]}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}


def _run_blender_preflight(arguments: dict[str, Any]) -> dict[str, Any]:
    """Discover Blender locally and query its version without creating a scene."""
    from local_agent.blender_workflow import discover_blender
    return discover_blender()


def _run_blender_inspect_mia_project(arguments: dict[str, Any]) -> dict[str, Any]:
    """Inspect a generated project structurally using a bundled read-only script."""
    from local_agent.blender_workflow import BlenderWorkflowError, inspect_mia_project
    try:
        return inspect_mia_project(arguments["project_name"])
    except BlenderWorkflowError as exc:
        return {"status": "rejected", "reason": str(exc)[:1000]}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}


def _run_blender_open_mia_project(arguments: dict[str, Any]) -> dict[str, Any]:
    """Open a generated Mia project in Blender's GUI using a fixed local path."""
    from local_agent.blender_workflow import BlenderWorkflowError, open_mia_project
    try:
        return open_mia_project(arguments["project_name"])
    except BlenderWorkflowError as exc:
        return {"status": "rejected", "reason": str(exc)[:1000]}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}


def _run_blender_mia_blockout(arguments: dict[str, Any]) -> dict[str, Any]:
    """Create and validate the fixed Mia starter blockout using local Blender."""
    from local_agent.blender_workflow import BlenderWorkflowError, create_mia_blockout
    try:
        return create_mia_blockout(arguments["project_name"])
    except BlenderWorkflowError as exc:
        return {"status": "rejected", "reason": str(exc)[:1000]}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}


def _run_blender_mia_skeleton(arguments: dict[str, Any]) -> dict[str, Any]:
    """Build a fixed skeleton prototype for an existing local Mia blockout."""
    from local_agent.blender_rigging import create_mia_skeleton
    return create_mia_skeleton(arguments["project_name"])


def _run_blender_knowledge_search(arguments: dict[str, Any]) -> dict[str, Any]:
    """Search the bundled read-only Blender knowledge base; never executes code."""
    from local_agent.blender_knowledge import search_knowledge
    results = search_knowledge(arguments["query"], arguments.get("limit", 5))
    return {
        "status": "completed",
        "task": "blender_knowledge_search",
        "query": arguments["query"][:1000],
        "results": results,
        "result_count": len(results),
        "note": "Guidance only; verify version-specific behavior and validate changes in Blender.",
    }


def _load_state() -> dict[str, Any]:
    """Load replay-protection state; fail closed if an existing file is unreadable."""
    if STATE_PATH.is_symlink() or getattr(STATE_PATH, "is_junction", lambda: False)():
        raise RuntimeError("poller state must not be a symlink or junction; refusing to run tasks")
    if STATE_PATH.parent == ROOT / ".local_agent":
        _ensure_agent_dir()
    try:
        raw = STATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise RuntimeError("poller state exists but cannot be read; refusing to run tasks") from exc
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError("poller state is invalid JSON; refusing to run tasks") from exc
    if not isinstance(data, dict):
        raise RuntimeError("poller state must be a JSON object; refusing to run tasks")
    processed = data.get("processed_tasks", {})
    if not isinstance(processed, dict):
        raise RuntimeError("poller replay history is invalid; refusing to run tasks")
    for task_id, record in processed.items():
        if not isinstance(task_id, str) or not isinstance(record, dict):
            raise RuntimeError("poller replay history is invalid; refusing to run tasks")
        if not isinstance(record.get("manifest_sha"), str):
            raise RuntimeError("poller replay history is incomplete; refusing to run tasks")
    return data


def _save_state(data: dict[str, Any]) -> None:
    if STATE_PATH.is_symlink() or getattr(STATE_PATH, "is_junction", lambda: False)():
        raise RuntimeError("poller state must not be a symlink or junction")
    if STATE_PATH.parent == ROOT / ".local_agent":
        parent = _ensure_agent_dir()
    else:
        parent = STATE_PATH.parent
        parent.mkdir(parents=True, exist_ok=True)
        if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
            raise RuntimeError("poller state directory must not be a symlink or junction")
    descriptor, temp_name = tempfile.mkstemp(prefix="poller_state.", suffix=".tmp", dir=str(parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        if STATE_PATH.is_symlink() or getattr(STATE_PATH, "is_junction", lambda: False)():
            raise RuntimeError("poller state became a symlink during save")
        os.replace(temp, STATE_PATH)
    except BaseException:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise



def classify_manifest(state: dict[str, Any], task_id: str, manifest_sha: str) -> str:
    """Classify mailbox content with bounded, persistent task-ID idempotency."""
    processed = state.get("processed_tasks", {})
    if not isinstance(processed, dict):
        processed = {}
    record = processed.get(task_id)
    if isinstance(record, dict):
        if manifest_sha == record.get("manifest_sha") or manifest_sha == record.get("rejected_sha"):
            return "same"
        return "reused_id"
    # Migrate old state files safely.
    if task_id == state.get("last_task_id"):
        if manifest_sha == state.get("manifest_sha"):
            return "same"
        return "reused_id"
    return "new"


def _remember_manifest(
    state: dict[str, Any], task_id: str, manifest_sha: str, *,
    rejected: bool = False, status: str | None = None,
) -> dict[str, Any]:
    """Persist bounded task identity history; task IDs are immutable."""
    processed = state.get("processed_tasks", {})
    if not isinstance(processed, dict):
        processed = {}
    record = processed.get(task_id)
    if not isinstance(record, dict):
        record = {"manifest_sha": manifest_sha}
    elif rejected:
        record = {**record, "rejected_sha": manifest_sha}
    if status:
        record = {**record, "status": status}
    processed[task_id] = record
    # Keep newest 200 IDs so state cannot grow without bound.
    processed = dict(list(processed.items())[-200:])
    return {
        "last_task_id": task_id,
        "manifest_sha": manifest_sha,
        "processed_tasks": processed,
    }

def _not_expired(task: Any) -> bool:
    try:
        now = datetime.now(timezone.utc)
        expiry = datetime.fromisoformat(task.expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            return False
        # Real protocol envelopes include created_at. Allow small clock skew,
        # but reject tasks that claim to have been created materially in the future.
        created_raw = getattr(task, "created_at", None)
        if created_raw is not None:
            if not isinstance(created_raw, str):
                return False
            created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            if created.tzinfo is None or created > now + timedelta(minutes=5):
                return False
        return expiry > now
    except (ValueError, TypeError):
        return False


def _run_one(client: GitHubQueueClient, task: Any, expected_manifest_sha: str | None = None) -> None:
    if not _not_expired(task):
        _publish_result_durable(client, task.task_id, {
            "task_id": task.task_id, "status": "rejected", "reason": "expired_or_invalid_expiry"
        })
        return
    handler = SUPPORTED_HANDLERS.get(task.operation)
    if handler is None and task.operation not in {"apply_patch", "blender_forest_preview", "save_story_plan", "compile_story_plan", "scan_project_assets", "blender_knowledge_search", "blender_preflight", "blender_mia_blockout", "blender_open_mia_project", "blender_inspect_mia_project", "blender_mia_skeleton"}:
        _publish_result_durable(client, task.task_id, {
            "task_id": task.task_id,
            "status": "unsupported",
            "reason": "operation_has_no_implemented_local_handler",
            "supported_operations": sorted(SUPPORTED_HANDLERS),
        })
        return
    print(f"\nNew task: {task.task_id} | operation={task.operation}")
    print("Arguments:", json.dumps(_redact_value(task.arguments), ensure_ascii=False))
    print("Supported operations: diagnostics, reviewed patches, story-plan storage/compilation, local asset indexing, Blender knowledge lookup, Blender discovery, Mia blockout creation, and the allowlisted forest preview.")
    if getattr(task, "requires_local_approval", True) is False:
        if os.environ.get("LOCAL_AGENT_ALLOW_REMOTE_APPROVAL") != "1" or task.operation not in REMOTE_APPROVABLE_OPERATIONS:
            result = {"task_id": task.task_id, "status": "blocked", "reason": "remote_approval_not_enabled_or_operation_not_allowlisted"}
            commit_sha = _publish_result_durable(client, task.task_id, result)
            print(f"Remote approval blocked by local policy. Result commit: {commit_sha}")
            return
        answer = "YES"  # Explicit task authorization plus local opt-in; no shell/code payloads are accepted.
    else:
        if not sys.stdin.isatty():
            result = {"task_id": task.task_id, "status": "blocked", "reason": "local_console_approval_required_but_no_interactive_console"}
            commit_sha = _publish_result_durable(client, task.task_id, result)
            print(f"Local approval required; non-interactive runner blocked the task. Result commit: {commit_sha}")
            return
        answer = input("Approve this local operation? Type YES to run: ").strip()
    if answer != "YES":
        result = {"task_id": task.task_id, "status": "declined", "reason": "local_user_declined"}
    else:
        # Re-read the desired manifest after local approval. If a newer task
        # replaced this one while the prompt was open, do not apply stale work.
        try:
            latest = client.fetch_desired_task()
            if latest is None:
                result = {
                    "task_id": task.task_id,
                    "status": "superseded",
                    "reason": "desired_task_removed_before_execution",
                }
                commit_sha = _publish_result_durable(client, task.task_id, result)
                print(f"Task removed before execution. Result commit: {commit_sha}")
                return
            latest_task, latest_manifest_sha = latest
            # Compare both the raw manifest revision and validated envelope, not just task_id. If a
            # mailbox writer accidentally reuses an ID with changed arguments,
            # the approved object must not be silently replaced underneath us.
            if latest_task != task or (expected_manifest_sha is not None and latest_manifest_sha != expected_manifest_sha):
                result = {
                    "task_id": task.task_id,
                    "status": "superseded",
                    "superseded_by": latest_task.task_id,
                    "reason": "desired_task_changed_after_approval",
                }
                commit_sha = _publish_result_durable(client, task.task_id, result)
                print(f"Task changed before execution. Result commit: {commit_sha}")
                return
            # A task can expire while the local approval prompt is open.
            if not _not_expired(latest_task):
                result = {
                    "task_id": task.task_id,
                    "status": "rejected",
                    "reason": "expired_while_waiting_for_local_approval",
                }
                commit_sha = _publish_result_durable(client, task.task_id, result)
                print(f"Task expired before execution. Result commit: {commit_sha}")
                return
            if task.operation == "apply_patch":
                details = _apply_patch(task.arguments["patch"], task.task_id)
            elif task.operation == "blender_forest_preview":
                details = _run_blender_forest_preview(task.arguments)
            elif task.operation == "save_story_plan":
                details = _run_save_story_plan(task.arguments)
            elif task.operation == "compile_story_plan":
                details = _run_compile_story_plan(task.arguments)
            elif task.operation == "scan_project_assets":
                details = _run_scan_project_assets(task.arguments)
            elif task.operation == "blender_knowledge_search":
                details = _run_blender_knowledge_search(task.arguments)
            elif task.operation == "blender_preflight":
                details = _run_blender_preflight(task.arguments)
            elif task.operation == "blender_mia_blockout":
                details = _run_blender_mia_blockout(task.arguments)
            elif task.operation == "blender_open_mia_project":
                details = _run_blender_open_mia_project(task.arguments)
            elif task.operation == "blender_inspect_mia_project":
                details = _run_blender_inspect_mia_project(task.arguments)
            elif task.operation == "blender_mia_skeleton":
                details = _run_blender_mia_skeleton(task.arguments)
            else:
                details = handler()
            result_status = details.get("status", "completed")
            result = {"task_id": task.task_id, "status": result_status, "details": details}
        except Exception as exc:  # Keep error details bounded and avoid leaking tracebacks.
            result = {"task_id": task.task_id, "status": "error", "error_type": type(exc).__name__}
    # Attach a deterministic diagnosis to failed outcomes. This suggests next
    # steps only; it never edits files or runs commands by itself.
    outcome = str(result.get("status", "unknown")).lower()
    failed_outcomes = {
        "error", "failed", "failed_rolled_back", "failed_needs_user",
        "blocked", "rejected", "unsupported", "timeout", "interrupted",
        "superseded",
    }
    if outcome in failed_outcomes:
        try:
            diagnostic_input = json.dumps(result, ensure_ascii=False, default=str)
            result["diagnosis"] = diagnose_error(diagnostic_input)
        except Exception:
            # Diagnostics must never prevent durable reporting of the original failure.
            result["diagnosis"] = {
                "rule_id": "diagnostic-engine-error",
                "escalate": True,
                "auto_fix_allowed": False,
                "note": "Error knowledge base failed; preserve original task result and escalate.",
            }

    # Save a durable local report before attempting network publication. If GitHub
    # is unavailable, the report still exists for diagnosis on this computer.
    try:
        report_path = write_report(
            _ensure_agent_dir() / "reports",
            kind="task",
            status=str(result.get("status", "unknown")),
            details={
                "task_id": task.task_id,
                "operation": task.operation,
                "result": result,
                "reporting_stage": "before_github_publication",
            },
        )
        result["local_report_path"] = str(report_path)
    except (OSError, RuntimeError) as exc:
        report_path = None
        print(f"Could not write local task report: {type(exc).__name__}")

    outcome = str(result.get("status", "unknown")).lower()
    failed_outcomes = {
        "error", "failed", "failed_rolled_back", "failed_needs_user",
        "blocked", "rejected", "unsupported", "timeout", "interrupted",
        "superseded",
    }
    if outcome in failed_outcomes:
        report_location = str(report_path) if report_path else "local report could not be written"
        notify_user(
            title=f"Local agent: task {task.task_id} needs attention",
            message=f"Outcome: {outcome}. Open .local_agent/reports for details.",
        )

    try:
        commit_sha = _publish_result_durable(client, task.task_id, result)
        print(f"Result published. GitHub commit: {commit_sha}")
    except QueueTransportError as exc:
        # Do not discard local evidence when the mailbox is temporarily offline.
        print(f"Result publication failed; local report retained: {type(exc).__name__}")



def _acquire_instance_lock(path: Path):
    """Acquire an OS-released singleton lock so two pollers cannot run one task twice."""
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise RuntimeError("poller lock file must not be a symlink or junction")
    if path.parent.is_symlink() or getattr(path.parent, "is_junction", lambda: False)():
        raise RuntimeError("poller lock directory must not be a symlink or junction")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("another local agent poller is already running") from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("another local agent poller is already running") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        return handle
    except Exception:
        handle.close()
        raise


def main() -> int:
    try:
        config = QueueConfig.from_environment()
        client = GitHubQueueClient(config)
    except Exception as exc:
        print(f"Cannot start mailbox poller: {type(exc).__name__}: {exc}")
        return 2

    try:
        lock_handle = _acquire_instance_lock(STATE_PATH.with_name("poller.lock"))
    except RuntimeError as exc:
        print(f"Cannot start poller: {exc}")
        return 2

    try:
        state = _load_state()
    except RuntimeError as exc:
        lock_handle.close()
        print(f"Cannot load poller replay state: {exc}")
        return 2

    interval = max(5, min(int(os.environ.get("LOCAL_AGENT_POLL_SECONDS", "10")), 30))
    backoff = interval
    last_seen = state.get("last_task_id")
    last_sha = state.get("manifest_sha")
    print(f"Polling private GitHub mailbox every {interval}s. Press Ctrl+C to stop.")
    print("This poller supports diagnostics, reviewed patches, story-plan storage/compilation, local asset indexing, and locally approved Blender forest previews; runtime tests remain outstanding.")

    try:
        while True:
            try:
                result_outbox = _result_outbox()
                pending_before_flush = result_outbox.pending_task_ids()
                pending_results = result_outbox.flush(client)
                if pending_results["published"] or pending_results["invalid"]:
                    print(f"Pending results: published={pending_results['published']}, deferred={pending_results['deferred']}, invalid={pending_results['invalid']}")
                fetched = client.fetch_desired_task()
                if fetched is not None:
                    task, manifest_sha = fetched
                    decision = classify_manifest(state, task.task_id, manifest_sha)
                    if decision == "new":
                        # Persist a claim before doing any local work. If the process
                        # dies or result publication fails, never blindly replay it.
                        state = _remember_manifest(
                            state, task.task_id, manifest_sha, status="in_progress"
                        )
                        _save_state(state)
                        _run_one(client, task, manifest_sha)
                        last_seen, last_sha = task.task_id, manifest_sha
                        state = _remember_manifest(
                            state, last_seen, last_sha, status="processed"
                        )
                        _save_state(state)
                    elif decision == "same":
                        record = state.get("processed_tasks", {}).get(task.task_id, {})
                        if isinstance(record, dict) and record.get("status") == "in_progress":
                            # A durable result may have been written just before a crash.
                            # Never overwrite it with a synthetic interrupted result.
                            if task.task_id in pending_before_flush:
                                if task.task_id in result_outbox.pending_task_ids():
                                    print(f"Task {task.task_id} has a pending result that needs delivery or repair; preserving it.")
                                else:
                                    state = _remember_manifest(
                                        state, task.task_id, manifest_sha, status="processed"
                                    )
                                    _save_state(state)
                            else:
                                # No durable result exists: execution outcome is uncertain.
                                _publish_result_durable(client, task.task_id, {
                                    "task_id": task.task_id,
                                    "status": "interrupted",
                                    "reason": "outcome_uncertain_requires_local_inspection_before_retry",
                                })
                                state = _remember_manifest(
                                    state, task.task_id, manifest_sha, status="interrupted"
                                )
                                _save_state(state)
                    elif decision == "reused_id":
                        # Task IDs are immutable. A changed manifest with the same ID
                        # is rejected, never silently re-executed.
                        _publish_result_durable(client, task.task_id, {
                            "task_id": task.task_id,
                            "status": "rejected",
                            "reason": "task_id_reused_with_different_manifest",
                        })
                        last_sha = manifest_sha
                        state = _remember_manifest(state, task.task_id, manifest_sha, rejected=True)
                        _save_state(state)
                backoff = interval
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\nPoller stopped.")
                return 0
            except QueueTransportError as exc:
                print(f"Mailbox check failed: {exc}. Retry in {backoff}s.")
                time.sleep(backoff)
                backoff = min(max(interval, backoff * 2), 300)
            except (OSError, ValueError) as exc:
                print(f"Poller local error: {type(exc).__name__}. Retry in {backoff}s.")
                time.sleep(backoff)
                backoff = min(max(interval, backoff * 2), 300)
    
    finally:
        lock_handle.close()

if __name__ == "__main__":
    raise SystemExit(main())
