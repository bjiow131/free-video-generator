"""Interactive GitHub mailbox poller for bounded diagnostics and reviewed patches.

This is an initial, single-agent prototype. It is not a general coding agent:
it supports fixed diagnostics and a bounded git patch after local approval.
Service start/stop/backup operations are not implemented.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from local_agent.cli import doctor, run_tests, status, tail_logs
from local_agent.github_queue import GitHubQueueClient, QueueConfig, QueueTransportError

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / ".local_agent" / "poller_state.json"
SUPPORTED_HANDLERS = {
    "doctor": doctor,
    "status": status,
    "logs": tail_logs,
    "test": run_tests,
}


def _apply_patch(patch: str) -> dict[str, Any]:
    """Apply a bounded git diff only after explicit local approval."""
    if not (ROOT / ".git").exists():
        return {"status": "blocked", "reason": "project_root_is_not_a_git_checkout"}
    try:
        check = subprocess.run(
            ["git", "apply", "--check"],
            cwd=ROOT, input=patch, capture_output=True, text=True,
            timeout=30, check=False, shell=False,
        )
        if check.returncode != 0:
            return {
                "status": "rejected",
                "reason": "git_apply_check_failed",
                "stderr_tail": [line[:1000] for line in check.stderr.splitlines()[-30:]],
            }
        applied = subprocess.run(
            ["git", "apply"],
            cwd=ROOT, input=patch, capture_output=True, text=True,
            timeout=30, check=False, shell=False,
        )
        if applied.returncode != 0:
            return {
                "status": "failed",
                "reason": "git_apply_failed",
                "stderr_tail": [line[:1000] for line in applied.stderr.splitlines()[-30:]],
            }
        return {"status": "applied", "test_run": False}
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "timeout_seconds": 30}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}


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


def _load_state() -> dict[str, Any]:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(data: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(STATE_PATH)


def _not_expired(task: Any) -> bool:
    try:
        expiry = datetime.fromisoformat(task.expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            return False
        return expiry > datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


def _run_one(client: GitHubQueueClient, task: Any) -> None:
    if not _not_expired(task):
        client.publish_result(task.task_id, {
            "task_id": task.task_id, "status": "rejected", "reason": "expired_or_invalid_expiry"
        })
        return
    handler = SUPPORTED_HANDLERS.get(task.operation)
    if handler is None and task.operation not in {"apply_patch", "blender_forest_preview", "save_story_plan", "compile_story_plan", "scan_project_assets"}:
        client.publish_result(task.task_id, {
            "task_id": task.task_id,
            "status": "unsupported",
            "reason": "operation_has_no_implemented_local_handler",
            "supported_operations": sorted(SUPPORTED_HANDLERS),
        })
        return
    print(f"\nNew task: {task.task_id} | operation={task.operation}")
    print("Arguments:", json.dumps(task.arguments, ensure_ascii=False))
    print("Supported operations: diagnostics, reviewed patches, story-plan storage/compilation, local asset indexing, and the allowlisted local Blender forest preview.")
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
                commit_sha = client.publish_result(task.task_id, result)
                print(f"Task removed before execution. Result commit: {commit_sha}")
                return
            latest_task = latest[0]
            # Compare the complete validated envelope, not just task_id. If a
            # mailbox writer accidentally reuses an ID with changed arguments,
            # the approved object must not be silently replaced underneath us.
            if latest_task != task:
                result = {
                    "task_id": task.task_id,
                    "status": "superseded",
                    "superseded_by": latest_task.task_id,
                    "reason": "desired_task_changed_after_approval",
                }
                commit_sha = client.publish_result(task.task_id, result)
                print(f"Task changed before execution. Result commit: {commit_sha}")
                return
            # A task can expire while the local approval prompt is open.
            if not _not_expired(latest_task):
                result = {
                    "task_id": task.task_id,
                    "status": "rejected",
                    "reason": "expired_while_waiting_for_local_approval",
                }
                commit_sha = client.publish_result(task.task_id, result)
                print(f"Task expired before execution. Result commit: {commit_sha}")
                return
            if task.operation == "apply_patch":
                details = _apply_patch(task.arguments["patch"])
            elif task.operation == "blender_forest_preview":
                details = _run_blender_forest_preview(task.arguments)
            elif task.operation == "save_story_plan":
                details = _run_save_story_plan(task.arguments)
            elif task.operation == "compile_story_plan":
                details = _run_compile_story_plan(task.arguments)
            elif task.operation == "scan_project_assets":
                details = _run_scan_project_assets(task.arguments)
            else:
                details = handler()
            result_status = details.get("status", "completed")
            result = {"task_id": task.task_id, "status": result_status, "details": details}
        except Exception as exc:  # Keep error details bounded and avoid leaking tracebacks.
            result = {"task_id": task.task_id, "status": "error", "error_type": type(exc).__name__}
    commit_sha = client.publish_result(task.task_id, result)
    print(f"Result published. GitHub commit: {commit_sha}")


def main() -> int:
    try:
        config = QueueConfig.from_environment()
        client = GitHubQueueClient(config)
    except Exception as exc:
        print(f"Cannot start mailbox poller: {type(exc).__name__}: {exc}")
        return 2

    interval = max(5, min(int(os.environ.get("LOCAL_AGENT_POLL_SECONDS", "10")), 30))
    backoff = interval
    last_seen = _load_state().get("last_task_id")
    print(f"Polling private GitHub mailbox every {interval}s. Press Ctrl+C to stop.")
    print("This poller supports diagnostics, reviewed patches, story-plan storage/compilation, local asset indexing, and locally approved Blender forest previews; runtime tests remain outstanding.")

    while True:
        try:
            fetched = client.fetch_desired_task()
            if fetched is not None:
                task, manifest_sha = fetched
                if task.task_id != last_seen:
                    _run_one(client, task)
                    last_seen = task.task_id
                    _save_state({"last_task_id": last_seen, "manifest_sha": manifest_sha})
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


if __name__ == "__main__":
    raise SystemExit(main())
