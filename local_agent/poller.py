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
from local_agent.result_outbox import ResultOutbox
from local_agent.reporting import _redact_value, write_report
from local_agent.error_knowledge import diagnose_error
from local_agent.notifications import notify_user
from local_agent.repair_channel import fetch_repair, RepairProtocolError, _validate_patch_paths
from local_agent.test_scope import test_command
from local_agent.blender_locator import find_blender_executable
from local_agent.mailbox_policy import (
    MailboxPolicyError, load_policy, is_auto_authorized, reserve_octava_call,
)
from local_agent.trusted_updates import TrustedUpdateError, get_opt_in, process_pending, recover_interrupted

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

def _task_delivery_status(task_id: str, pending_task_ids: set[str]) -> str:
    """Distinguish a published result from one safely queued for later delivery."""
    return "pending_delivery" if task_id in pending_task_ids else "processed"

def _manifest_collision_result_id(task_id: str, manifest_sha: str) -> str:
    """Deterministic, isolated result key for a rejected immutable-ID collision.

    Do not use the original task ID: that output must remain unchanged forever.
    Deriving the ID from both values avoids path injection and makes delivery
    idempotent even if the process exits before the local state is saved.
    """
    import hashlib

    digest = hashlib.sha256(
        (task_id + "\\n" + manifest_sha).encode("utf-8")
    ).hexdigest()[:32]
    return f"task-id-reuse-{digest}"




def doctor_with_supervisor() -> dict[str, Any]:
    """Read-only Windows watchdog health; never reveal account names or secrets."""
    result = doctor()
    if os.name != "nt":
        return result
    autostart = False
    scheduled = False
    recent = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            value, _ = winreg.QueryValueEx(key, "BlenderOctavaStudioSupervisor")
        autostart = (isinstance(value, str) and
                     "run_github_mailbox_agent.bat" in value.casefold() and
                     str(ROOT).casefold() in value.casefold())
    except (OSError, ImportError, ValueError):
        pass
    try:
        found = subprocess.run(
            ["schtasks.exe", "/Query", "/TN", "BlenderOctavaStudioSupervisor"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, timeout=8, check=False, shell=False)
        scheduled = found.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        pass
    logfile = ROOT / ".local_agent" / "octava_supervisor.log"
    if logfile.is_file() and not logfile.is_symlink():
        try:
            with logfile.open("rb") as stream:
                stream.seek(max(0, logfile.stat().st_size - 5000))
                # Only event categories, not arbitrary on-disk message text.
                tail = stream.read(5000).decode("utf-8", errors="replace")
            tags = ("Started mailbox service", "Started studio service",
                    "Per-user Windows login autostart registered",
                    "Scheduled supervisor recovery installed",
                    "Scheduled recovery unavailable",
                    "Trusted update installed; controlled restart")
            recent = [tag for tag in tags if tag in tail]
        except OSError:
            pass
    result["windows_supervisor"] = {
        "autostart_after_user_login": autostart,
        "scheduled_recovery_registered": scheduled,
        "log_detected": logfile.is_file(),
        "recent_event_types": recent,
        "service_restart_check_seconds": 2,
    }
    return result


SUPPORTED_HANDLERS = {
    "doctor": doctor_with_supervisor,
    "preflight": preflight,
    "status": status,
    "logs": tail_logs,
    "test": run_tests,
}


def _apply_patch(patch: str, task_id: str, expected_base_sha: str | None = None) -> dict[str, Any]:
    """Apply and test a patch in an isolated Git worktree, never in the active checkout."""
    import re

    # Both mailbox entry points must enforce the same path and file-type restrictions.
    # Do this before creating a branch or worktree, even for a direct apply_patch task.
    try:
        _validate_patch_paths(patch)
    except (RepairProtocolError, TypeError):
        return {"status": "rejected", "reason": "unsafe_or_malformed_patch"}
    if not (ROOT / ".git").exists():
        return {"status": "blocked", "reason": "project_root_is_not_a_git_checkout"}
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "-", task_id)[:80]
    if not safe_id:
        return {"status": "blocked", "reason": "invalid_task_id_for_isolated_worktree"}

    branch = f"agent/task-{safe_id}"
    parent_root = ROOT.parent.resolve()
    worktree_root = ROOT.parent / ".local_agent_worktrees"
    if worktree_root.is_symlink() or getattr(worktree_root, "is_junction", lambda: False)():
        return {"status": "blocked", "reason": "worktree_root_must_not_be_symlink_or_junction"}
    try:
        worktree_root.mkdir(parents=True, exist_ok=True)
        if worktree_root.resolve().parent != parent_root:
            return {"status": "blocked", "reason": "worktree_root_resolves_outside_expected_parent"}
    except OSError as exc:
        return {"status": "error", "reason": "could_not_prepare_worktree_root", "error_type": type(exc).__name__}
    worktree = worktree_root / f"task-{safe_id}"
    if worktree.exists() or worktree.is_symlink() or getattr(worktree, "is_junction", lambda: False)():
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

    worktree_created = False
    creation_attempted = False
    try:
        head = run_git(["rev-parse", "--verify", "HEAD"])
        if head.returncode != 0:
            return {"status": "blocked", "reason": "could_not_resolve_base_commit"}
        base_sha = head.stdout.strip()
        if expected_base_sha is not None and base_sha != expected_base_sha:
            return {"status": "rejected", "reason": "base_commit_mismatch", "expected_base_commit": expected_base_sha, "actual_base_commit": base_sha}
        branch_check = run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"])
        if branch_check.returncode == 0:
            return {
                "status": "blocked",
                "reason": "task_branch_already_exists; inspect it before retrying",
                "branch": branch,
            }

        creation_attempted = True
        created = run_git(["worktree", "add", "-b", branch, str(worktree), base_sha], timeout=120)
        if created.returncode != 0:
            return {
                "status": "failed_needs_user",
                "reason": "worktree_creation_failed_inspect_for_partial_worktree_or_branch",
                "worktree": str(worktree),
                "branch": branch,
                "stderr_tail": [line[:500] for line in created.stderr.splitlines()[-20:]],
            }
        worktree_created = True

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

        # Stage the approved change BEFORE running tests: test side-effects must
        # never become part of the repair commit.
        patch_paths = sorted({
            line.split()[2][2:]
            for line in patch.splitlines() if line.startswith("diff --git ")
        })
        staged = run_git(["add", "--", *patch_paths], cwd=worktree, timeout=60)
        if staged.returncode != 0:
            return _discard_failed_worktree(
                run_git, worktree, branch,
                {"status": "failed_rolled_back", "reason": "repair_patch_paths_could_not_be_staged"},
            )
        staged_check = run_git(["diff", "--cached", "--check"], cwd=worktree, timeout=60)
        if staged_check.returncode != 0:
            return _discard_failed_worktree(
                run_git, worktree, branch,
                {"status": "failed_rolled_back", "reason": "staged_diff_check_failed"},
            )
        staged_snapshot = run_git(
            ["diff", "--cached", "--no-ext-diff", "--binary"], cwd=worktree, timeout=60,
        )
        if staged_snapshot.returncode != 0:
            return _discard_failed_worktree(
                run_git, worktree, branch,
                {"status": "failed_rolled_back", "reason": "could_not_snapshot_staged_patch"},
            )

        try:
            tests = subprocess.run(
                test_command("all", root=worktree),
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

        whitespace = run_git(["diff", "--check"], cwd=worktree, timeout=60)
        if whitespace.returncode != 0:
            return _discard_failed_worktree(
                run_git, worktree, branch,
                {"status": "failed_rolled_back", "reason": "git_diff_check_failed",
                 "stderr_tail": [line[:500] for line in whitespace.stderr.splitlines()[-20:]]},
            )

        # Tests can modify repository files and even invoke Git. Fail closed
        # rather than committing anything other than the already tested patch.
        unstaged = run_git(["diff", "--exit-code", "--"], cwd=worktree, timeout=60)
        current_staged = run_git(
            ["diff", "--cached", "--no-ext-diff", "--binary"], cwd=worktree, timeout=60,
        )
        if (unstaged.returncode != 0 or current_staged.returncode != 0
                or current_staged.stdout != staged_snapshot.stdout):
            return _discard_failed_worktree(
                run_git, worktree, branch,
                {"status": "failed_rolled_back", "reason": "post_patch_tests_modified_worktree_or_index"},
            )
        staged_diff = run_git(["diff", "--cached", "--check"], cwd=worktree, timeout=60)
        if staged_diff.returncode != 0:
            return _discard_failed_worktree(
                run_git, worktree, branch,
                {"status": "failed_rolled_back", "reason": "staged_diff_check_failed"},
            )
        commit = run_git([
            "-c", "user.name=Blender Work Agent",
            "-c", "user.email=blender-work-agent@users.noreply.github.com",
            "commit", "-m", f"Apply reviewed repair {safe_id}",
        ], cwd=worktree, timeout=120)
        if commit.returncode != 0:
            return {
                "status": "completed_needs_review",
                "reason": "tests_passed_but_local_repair_commit_failed",
                "base_commit": base_sha, "branch": branch, "worktree": str(worktree),
                "stderr_tail": [line[:500] for line in commit.stderr.splitlines()[-20:]],
                "active_checkout_modified": False,
            }
        commit_sha = run_git(["rev-parse", "--verify", "HEAD"], cwd=worktree, timeout=15)
        return {
            "status": "completed",
            "reason": "patch_applied_tested_and_committed_in_isolated_worktree",
            "base_commit": base_sha,
            "repair_commit": commit_sha.stdout.strip() if commit_sha.returncode == 0 else None,
            "branch": branch,
            "worktree": str(worktree),
            "test_return_code": tests.returncode,
            "requires_review_before_merge": True,
            "active_checkout_modified": False,
            "pushed_to_remote": False,
        }
    except (subprocess.TimeoutExpired, OSError) as exc:
        failure = {
            "status": "timeout" if isinstance(exc, subprocess.TimeoutExpired) else "error",
            "reason": "git_operation_timed_out" if isinstance(exc, subprocess.TimeoutExpired) else "git_operation_failed",
            "error_type": type(exc).__name__,
        }
        if worktree_created:
            return _discard_failed_worktree(run_git, worktree, branch, failure)
        if creation_attempted:
            return {
                "status": "failed_needs_user",
                "reason": "worktree_creation_interrupted_inspect_for_partial_worktree_or_branch",
                "original_failure": failure,
                "worktree": str(worktree),
                "branch": branch,
            }
        return failure


def _discard_failed_worktree(run_git, worktree: Path, branch: str, result: dict[str, Any]) -> dict[str, Any]:
    """Remove only the disposable worktree created for this task after a failure."""
    try:
        remove = run_git(["worktree", "remove", "--force", str(worktree)], timeout=120)
        # Never delete a branch while its worktree removal is unconfirmed.
        if remove.returncode != 0:
            return {
                "status": "failed_needs_user",
                "reason": "failed_task_worktree_removal",
                "original_failure": result,
                "worktree_remove_return_code": remove.returncode,
                "worktree": str(worktree),
                "branch": branch,
            }
        delete_branch = run_git(["branch", "-D", branch], timeout=60)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {
            "status": "failed_needs_user",
            "reason": "failed_task_cleanup_interrupted",
            "original_failure": result,
            "cleanup_error_type": type(exc).__name__,
            "worktree": str(worktree),
            "branch": branch,
        }
    if delete_branch.returncode != 0:
        return {
            "status": "failed_needs_user",
            "reason": "failed_task_branch_removal",
            "original_failure": result,
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


def _run_studio_camera_qa(workspace: str) -> dict[str, Any]:
    """Run a fixed 3s Blender animation headlessly and send its review to Dropbox.

    Does not change the installed studio_blender_scene.py, Studio project files,
    character assets, or the trusted updater allowlist. The sole Blender script
    is a validated private copy of the already-installed offline fixture, with
    a deterministic compatibility fix for Blender's missing World datablock.
    No script, shell command, filename, or prompt is accepted from GitHub.
    """
    import shutil
    import uuid
    from local_agent.studio_state import StudioStore, default_state
    from local_agent.prompt_interpreter import interpret_scene
    from local_agent.studio_server import export_review, read_settings

    project = "agent_camera_qa_" + uuid.uuid4().hex[:12]
    job_id = uuid.uuid4().hex
    output = None
    try:
        store = StudioStore(workspace, project=project)
        output = store.root / "studio_jobs" / job_id
        output.mkdir(parents=True, exist_ok=False)
        state = default_state(project)
        state["settings"].update({"duration": 3, "fps": 12, "resolution": "360x640"})
        plan = interpret_scene("тестовый персонаж идёт, камера следует за ним",
                               state, "camera_qa")
        if plan["readiness"] != "ready_fixture":
            raise ValueError("Fixed camera fixture is not renderable")
        (output / "manifest.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        blender = find_blender_executable()
        ffmpeg = shutil.which("ffmpeg")
        if blender is None or not ffmpeg:
            return {"status": "failed", "reason": "blender_or_ffmpeg_missing",
                    "project": project, "job_id": job_id}

        source = ROOT / "local_agent" / "studio_blender_scene.py"
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 200_000:
            raise ValueError("Untrusted or missing local Blender fixture")
        original = source.read_text(encoding="utf-8")
        marker = "    scene.world.color = (0.08, 0.11, 0.16)"
        if marker in original:
            if original.count(marker) != 1 or "    bpy.ops.wm.read_factory_settings(use_empty=True)" not in original:
                raise ValueError("Unexpected Blender fixture signature")
            original = original.replace(
                marker,
                '    if scene.world is None:\n'
                '        scene.world = bpy.data.worlds.new("Camera QA World")\n'
                + marker,
            )
        compile(original, str(source), "exec")
        script = output / "camera_fixture.py"
        with script.open("x", encoding="utf-8") as stream:
            stream.write(original)

        blender_cmd = [
            str(blender), "--background", "--factory-startup",
            "--disable-autoexec", "--offline-mode", "--python-exit-code", "12",
            "--python", str(script), "--",
            str(output / "manifest.json"), str(output),
        ]
        with (output / "blender.log").open("wb") as log:
            try:
                run = subprocess.run(
                    blender_cmd, cwd=output, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, shell=False,
                    timeout=480, check=False,
                )
            except subprocess.TimeoutExpired:
                return {"status": "failed", "reason": "blender_timeout_480s",
                        "project": project, "job_id": job_id}
        if run.returncode:
            lines = []
            with (output / "blender.log").open("rb") as log:
                log.seek(max(0, (output / "blender.log").stat().st_size - 8192))
                tail = log.read(8192).decode("utf-8", errors="replace")
            for raw in tail.splitlines():
                line = raw.strip()
                if line.startswith(("Traceback", "RuntimeError:", "AttributeError:",
                                    "TypeError:", "ValueError:", "Error:")):
                    lines.append(line[:160])
            return {"status": "failed", "reason": "blender_exit_" + str(run.returncode),
                    "blender_errors": lines[-8:], "project": project, "job_id": job_id}

        expected = plan["duration"] * plan["fps"]
        frames = sorted((output / "frames").glob("frame_*.png"))
        if len(frames) != expected or not (output / "scene.blend").is_file():
            return {"status": "failed", "reason": "incomplete_blender_frames",
                    "rendered_frames": len(frames), "expected_frames": expected,
                    "project": project, "job_id": job_id}
        cmd = [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-framerate", str(plan["fps"]), "-i", str(output / "frames" / "frame_%04d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(output / "scene.mp4"),
        ]
        with (output / "ffmpeg.log").open("wb") as log:
            try:
                merged = subprocess.run(
                    cmd, cwd=output, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, shell=False,
                    timeout=180, check=False,
                )
            except subprocess.TimeoutExpired:
                return {"status": "failed", "reason": "ffmpeg_timeout_180s",
                        "project": project, "job_id": job_id}
        video = output / "scene.mp4"
        if merged.returncode or not video.is_file() or video.stat().st_size < 100:
            return {"status": "failed", "reason": "ffmpeg_mp4_failed",
                    "project": project, "job_id": job_id}

        review = {"status": "disabled"}
        try:
            if read_settings()["enabled"]:
                review = export_review(
                    output,
                    {"job_id": job_id, "scene_id": "camera_qa", "kind": "scene",
                     "total_frames": expected},
                    ffmpeg,
                )
        except (OSError, ValueError) as exc:
            review = {"status": "failed", "reason": type(exc).__name__,
                      "message": str(exc)[:180]}
        status = "completed" if review.get("status") == "exported_to_local_dropbox" else "failed"
        return {
            "status": status,
            "mode": "procedural_camera_fixture",
            "project": project, "job_id": job_id,
            "video": str(video), "frames_expected": expected,
            "review_delivery": review, "cloud_sync_verified": False,
        }
    except (OSError, ValueError, SyntaxError) as exc:
        return {"status": "failed", "reason": type(exc).__name__,
                "message": str(exc)[:160], "mode": "procedural_camera_fixture",
                "project": project, "job_id": job_id}

def _reexport_existing_camera_qa(workspace: str) -> dict[str, Any]:
    """Retry only Dropbox delivery of a previously completed fixed QA MP4.

    Never rerenders Blender or touches a user's story projects. Accepts no
    filesystem path or shell command from the incoming GitHub task.
    """
    import shutil
    from local_agent.studio_server import export_review, read_settings
    root = Path(workspace).expanduser().resolve()
    if not read_settings()["enabled"]:
        return {"status": "failed", "reason": "dropbox_review_permission_disabled"}
    if not root.is_dir() or root.is_symlink():
        return {"status": "failed", "reason": "workspace_unavailable"}
    candidates = []
    for project in root.glob("agent_camera_qa_*"):
        if (not project.is_dir() or project.is_symlink()
                or getattr(project, "is_junction", lambda: False)()):
            continue
        jobs = project / "studio_jobs"
        if not jobs.is_dir() or jobs.is_symlink():
            continue
        for job in jobs.iterdir():
            if (not job.is_dir() or job.is_symlink()
                    or getattr(job, "is_junction", lambda: False)()
                    or len(job.name) != 32
                    or any(ch not in "0123456789abcdef" for ch in job.name)):
                continue
            video = job / "scene.mp4"
            planfile = job / "manifest.json"
            if (not video.is_file() or video.is_symlink()
                    or not planfile.is_file() or planfile.is_symlink()
                    or not 100 <= video.stat().st_size <= 32_000_000
                    or planfile.stat().st_size > 20_000):
                continue
            try:
                plan = json.loads(planfile.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                continue
            if (not isinstance(plan, dict) or plan.get("scene_id") != "camera_qa"
                    or plan.get("actor_kind") != "procedural_test_fixture"
                    or plan.get("camera") != "follow"
                    or plan.get("fps") != 12 or plan.get("duration") != 3):
                continue
            candidates.append((video.stat().st_mtime, job))
    if not candidates:
        return {"status": "failed", "reason": "no_completed_camera_qa_video"}
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"status": "failed", "reason": "ffmpeg_missing"}
    for _, job in candidates[:10]:
        try:
            result = export_review(
                job,
                {"job_id": job.name, "scene_id": "camera_qa",
                 "kind": "scene", "total_frames": 36},
                ffmpeg,
            )
        except (OSError, ValueError) as exc:
            # A previously exported review may be present. Try the next
            # completed QA job, but do not overwrite any Dropbox files.
            if "already exists" in str(exc):
                continue
            return {"status": "failed", "reason": type(exc).__name__,
                    "message": str(exc)[:180], "job_id": job.name}
        return {"status": "completed", "mode": "existing_camera_qa_export",
                "job_id": job.name, "review_delivery": result,
                "cloud_sync_verified": False}
    return {"status": "failed", "reason": "camera_reviews_already_exported"}


def _run_blender_forest_preview(arguments: dict[str, Any]) -> dict[str, Any]:
    """Run the single allowlisted Blender task using local-only configuration."""
    # The Studio launcher configures LOCAL_AGENT_WORKSPACE, but the GitHub
    # mailbox launcher may be started independently. Reuse the installation's
    # sibling workspace rather than refusing every otherwise safe Blender job.
    workspace = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not workspace:
        workspace = str(ROOT.parent / "AI-Agent-Workspace")
    if arguments["project_name"].startswith("qa_export_"):
        review = _reexport_existing_camera_qa(workspace)
        return {"status": review["status"], "task": "blender_forest_preview",
                "camera_video_qa": review}
    from local_agent.blender_bridge import BlenderBridge, BlenderBridgeError
    executable = find_blender_executable()
    if executable is None:
        return {
            "status": "blocked",
            "reason": "blender_executable_not_found",
            "remote_paths_or_commands_accepted": False,
        }
    try:
        bridge = BlenderBridge(executable, workspace)
        result = bridge.run_task(
            "forest_preview",
            project_name=arguments["project_name"],
            render=arguments.get("render", True),
            preview=arguments.get("preview", True),
            cycles=arguments.get("cycles", False),
        )
        if arguments.get("render", True) and arguments["project_name"].startswith("qa_camera_"):
            # Existing allowlisted forest task supports a fixed accompanying
            # camera fixture for end-to-end QA. No arbitrary remote inputs.
            video = _run_studio_camera_qa(workspace)
            return {"status": video["status"], "task": "blender_forest_preview",
                    "result": result, "camera_video_qa": video}
        return {"status": "completed", "task": "blender_forest_preview", "result": result}
    except BlenderBridgeError as exc:
        return {"status": "failed", "task": "blender_forest_preview", "reason": str(exc)[:1000]}


def _run_octava_advice(arguments: dict[str, Any]) -> dict[str, Any]:
    """One user-approved, locally opt-in advisory call, never executable code."""
    from local_agent.octava_advisor import request_advice
    return request_advice(arguments["prompt"])


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
    if len(processed) > 10000:
        raise RuntimeError("poller replay history capacity exceeded; refusing to run tasks")
    for task_id, record in processed.items():
        if not isinstance(task_id, str) or not isinstance(record, dict):
            raise RuntimeError("poller replay history is invalid; refusing to run tasks")
        if not isinstance(record.get("manifest_sha"), str):
            raise RuntimeError("poller replay history is incomplete; refusing to run tasks")
    repair_history = data.get("processed_repairs", {})
    if not isinstance(repair_history, dict) or len(repair_history) > 2000:
        raise RuntimeError("poller repair replay history is invalid or too large; refusing to run repairs")
    for repair_id, record in repair_history.items():
        if (not isinstance(repair_id, str) or not isinstance(record, dict)
                or not isinstance(record.get("manifest_sha"), str)):
            raise RuntimeError("poller repair replay history is incomplete; refusing to run repairs")
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
    previous = state.get("processed_tasks", {})
    if not isinstance(previous, dict):
        raise RuntimeError("Task replay history is invalid; refusing to discard existing state")
    # Copy before mutation, so rejecting a new ID at the capacity boundary
    # cannot corrupt the caller's in-memory replay protections.
    processed = dict(previous)
    record = processed.get(task_id)
    if not isinstance(record, dict):
        if len(processed) >= 10000:
            raise RuntimeError("Task replay history capacity reached; refusing new IDs")
        record = {"manifest_sha": manifest_sha}
    elif rejected:
        record = {**record, "rejected_sha": manifest_sha}
    if status:
        record = {**record, "status": status}
    processed[task_id] = record
    # Never evict replay tombstones: an old immutable task ID must stay known.
    if len(processed) > 10000:
        raise RuntimeError("Task replay history capacity reached; inspect and archive safely")
    return {
        **state,
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
    if handler is None and task.operation not in {"apply_patch", "blender_forest_preview", "save_story_plan", "compile_story_plan", "scan_project_assets", "blender_knowledge_search", "blender_preflight", "blender_mia_blockout", "blender_open_mia_project", "blender_inspect_mia_project", "blender_mia_skeleton", "octava_advice"}:
        _publish_result_durable(client, task.task_id, {
            "task_id": task.task_id,
            "status": "unsupported",
            "reason": "operation_has_no_implemented_local_handler",
            "supported_operations": sorted(SUPPORTED_HANDLERS),
        })
        return
    print(f"\nNew task: {task.task_id} | operation={task.operation}")
    print("Arguments:", json.dumps(_redact_value(task.arguments), ensure_ascii=False))
    # Remote tasks cannot grant themselves permission: the protocol always
    # requires local approval, satisfied either interactively or by an explicit
    # standing authorization stored only in the local Studio UI.
    if getattr(task, "requires_local_approval", True) is not True:
        result = {"task_id": task.task_id, "status": "blocked", "reason": "remote_approval_disabled"}
        commit_sha = _publish_result_durable(client, task.task_id, result)
        print(f"Remote approval is disabled. Result commit: {commit_sha}")
        return
    try:
        policy = load_policy()
    except MailboxPolicyError:
        result = {"task_id": task.task_id, "status": "blocked", "reason": "local_approval_policy_invalid"}
        _publish_result_durable(client, task.task_id, result)
        return
    unattended = policy["enabled"]
    if unattended and not is_auto_authorized(task.operation, policy):
        result = {"task_id": task.task_id, "status": "blocked", "reason": "operation_not_authorized_for_unattended_mode"}
        _publish_result_durable(client, task.task_id, result)
        print("Automatic task blocked by local allowlist; no console approval requested.")
        return
    if unattended:
        print("Authorized by persistent local Studio policy. No per-task YES needed.")
        approved = True
    else:
        if not sys.stdin.isatty():
            result = {"task_id": task.task_id, "status": "blocked", "reason": "local_console_approval_required_but_no_interactive_console"}
            _publish_result_durable(client, task.task_id, result)
            return
        approved = input("Approve this local operation? Type YES to run: ").strip() == "YES"
    if not approved:
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
            elif task.operation == "octava_advice":
                if unattended:
                    # Legacy hook is deliberately a no-op: the user removed the
                    # 20-per-day local quota. Local OctavAPI consent still applies.
                    reserve_octava_call()
                details = _run_octava_advice(task.arguments)
            else:
                details = handler()
            result_status = details.get("status", "completed")
            result = {"task_id": task.task_id, "status": result_status, "details": details}
        except Exception as exc:  # Keep error details bounded and avoid leaking tracebacks.
            # OctavAPI errors have fixed, deliberately redacted messages.
            # Preserve an actionable reason (e.g. insufficient balance) so the
            # user knows to rotate the key, without exposing any credential.
            from local_agent.octava_advisor import OctavaAdviceError
            result = {"task_id": task.task_id, "status": "error", "error_type": type(exc).__name__}
            if isinstance(exc, (OctavaAdviceError, MailboxPolicyError)):
                result["reason"] = str(exc)
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




def _poll_repair_once(client: GitHubQueueClient, state: dict[str, Any]) -> dict[str, Any]:
    """Fetch one ChatGPT-authored repair; require local approval and test in isolation."""
    try:
        fetched = fetch_repair(client)
    except QueueTransportError as exc:
        if "Mailbox item not found" not in str(exc):
            print(f"Repair channel unavailable: {type(exc).__name__}")
        return state
    except RepairProtocolError as exc:
        print(f"Repair rejected by protocol validation: {str(exc)[:240]}")
        return state
    except Exception as exc:
        print(f"Repair fetch failed safely: {type(exc).__name__}")
        return state
    if fetched is None:
        return state
    manifest, manifest_sha, patch = fetched

    def publish_repair_result(result: dict[str, Any]) -> None:
        try:
            _publish_result_durable(client, f"repair-{manifest['repair_id']}", result)
        except QueueTransportError:
            print("Repair result retained in local outbox; GitHub delivery will retry.")
    repair_id = manifest["repair_id"]
    processed = state.get("processed_repairs", {})
    if not isinstance(processed, dict):
        processed = {}
    previous = processed.get(repair_id)
    if isinstance(previous, dict):
        if previous.get("manifest_sha") != manifest_sha:
            # Keep the ORIGINAL manifest claim. Reusing a repair ID must not
            # rewrite either its durable replay history or its GitHub result.
            print(f"Repair {repair_id} rejected: immutable repair ID reused.")
            return state
        if previous.get("status") == "in_progress":
            # The process died or was interrupted before persisting a final
            # outcome. Never execute the same patch again on restart.
            print(f"Repair {repair_id} interrupted; inspect the local worktree and result outbox.")
            processed[repair_id] = {**previous, "status": "interrupted"}
            state = {**state, "processed_repairs": processed}
            _save_state(state)
        return state

    if len(processed) >= 2000:
        raise RuntimeError("Repair replay history capacity reached; refusing to accept new repair IDs")

    def record(status: str) -> dict[str, Any]:
        updated = dict(processed)
        updated[repair_id] = {"manifest_sha": manifest_sha, "status": status}
        if len(updated) > 2000:
            raise RuntimeError("Repair replay history capacity reached; refusing to evict repair IDs")
        return {**state, "processed_repairs": updated}

    print(f"\nNew repair available: {repair_id}")
    print(f"Target base commit: {manifest['base_commit_sha']}")
    print("Patch paths are restricted to local_agent/, tests/, docs/, scripts/, and approved root files.")
    # Path validation is not a sandbox: pytest will execute patched Python code.
    # Show the EXACT vetted patch before interactive local approval.
    try:
        # Never prompt unattended users for repair approval. Unknown patch code
        # could execute in pytest even if its paths are allowlisted.
        if load_policy()["enabled"]:
            result = {"task_id": f"repair-{repair_id}", "status": "blocked",
                      "reason": "repairs_always_require_interactive_review"}
            publish_repair_result(result)
            state = record("blocked")
            _save_state(state)
            return state
    except MailboxPolicyError:
        result = {"task_id": f"repair-{repair_id}", "status": "blocked",
                  "reason": "local_approval_policy_invalid"}
        publish_repair_result(result)
        state = record("blocked")
        _save_state(state)
        return state
    print("\n=== BEGIN REPAIR PATCH (REVIEW BEFORE APPROVING) ===")
    print(patch)
    print("=== END REPAIR PATCH ===")
    print("WARNING: tests may execute code from this patch with your local user permissions.")
    print("Do not approve code you have not reviewed.")
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=15, check=False, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = {"task_id": f"repair-{repair_id}", "status": "error", "reason": "could_not_check_local_base", "error_type": type(exc).__name__}
        publish_repair_result(result)
        state = record("error")
        _save_state(state)
        return state
    actual_base = head.stdout.strip() if head.returncode == 0 else ""
    if actual_base != manifest["base_commit_sha"]:
        result = {
            "task_id": f"repair-{repair_id}", "status": "rejected",
            "reason": "base_commit_mismatch", "expected_base_commit": manifest["base_commit_sha"],
            "actual_base_commit": actual_base or None,
        }
        publish_repair_result(result)
        state = record("rejected")
        _save_state(state)
        print("Repair rejected: local checkout is not at the required base commit.")
        return state
    if not sys.stdin.isatty():
        result = {"task_id": f"repair-{repair_id}", "status": "blocked", "reason": "local_console_approval_required"}
        publish_repair_result(result)
        state = record("blocked")
        _save_state(state)
        return state
    answer = input("After reviewing the full patch, apply in an isolated worktree and run tests? Type YES: ").strip()
    if answer != "YES":
        result = {"task_id": f"repair-{repair_id}", "status": "declined", "reason": "local_user_declined"}
        publish_repair_result(result)
        state = record("declined")
        _save_state(state)
        return state

    # Re-fetch after approval to prevent replacing the repair while the prompt is open.
    try:
        latest = fetch_repair(client)
        if latest is None or latest[1] != manifest_sha or latest[0] != manifest or latest[2] != patch:
            result = {"task_id": f"repair-{repair_id}", "status": "superseded", "reason": "repair_changed_after_approval"}
        elif not _not_expired(type("RepairExpiry", (), {"expires_at": manifest["expires_at"], "created_at": manifest["created_at"]})()):
            result = {"task_id": f"repair-{repair_id}", "status": "rejected", "reason": "repair_expired_while_waiting_for_approval"}
        else:
            # Claim the immutable repair BEFORE touching Git or executing pytest.
            # A crash must never replay an unknown-result repair automatically.
            state = record("in_progress")
            _save_state(state)
            details = _apply_patch(patch, f"repair-{repair_id}", expected_base_sha=manifest["base_commit_sha"])
            result = {"task_id": f"repair-{repair_id}", "status": details.get("status", "unknown"), "details": details}
            if details.get("status") == "completed" and details.get("repair_commit"):
                try:
                    diff = subprocess.run(
                        ["git", "diff", "--no-ext-diff", "--unified=3",
                         manifest["base_commit_sha"], details["repair_commit"]],
                        cwd=Path(details["worktree"]), capture_output=True,
                        text=True, timeout=30, check=False, shell=False,
                    )
                    if diff.returncode != 0 or not diff.stdout.startswith("diff --git "):
                        raise RuntimeError("could_not_build_tested_repair_diff")
                    if any(marker in diff.stdout for marker in (
                        "GIT binary patch", "Binary files ", "new file mode 120000",
                        "old mode 120000", "160000",
                    )):
                        raise RuntimeError("tested_repair_diff_contains_binary_or_special_files")
                    _validate_patch_paths(diff.stdout)
                    artifact = client.publish_repair_artifact(repair_id, diff.stdout)
                    result["tested_patch_artifact"] = artifact
                except Exception as exc:
                    result["status"] = "completed_local_only"
                    result["tested_patch_artifact"] = {
                        "status": "publish_failed",
                        "error_type": type(exc).__name__,
                    }
    except Exception as exc:
        result = {"task_id": f"repair-{repair_id}", "status": "error", "error_type": type(exc).__name__}
    publish_repair_result(result)
    state = record(str(result.get("status", "unknown")))
    _save_state(state)
    print(f"Repair {repair_id}: {result.get('status')}. Active checkout was not modified.")
    return state


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
    # Remote task intake is deliberately opt-in; the normal local Blender launcher
    # never starts a GitHub polling loop by accident.
    if os.environ.get("LOCAL_AGENT_ENABLE_GITHUB_MAILBOX") != "1":
        print("GitHub mailbox polling is disabled. Use run_github_mailbox_agent.bat or set LOCAL_AGENT_ENABLE_GITHUB_MAILBOX=1 explicitly.")
        return 2

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

    # If a previous Windows process crashed while swapping an authorized
    # release, restore the full previous set before doing any work.
    try:
        if recover_interrupted():
            print("Interrupted trusted update rolled back to local backup.")
    except TrustedUpdateError as exc:
        lock_handle.close()
        print(f"Cannot recover previous trusted update: {exc}")
        return 2

    interval = max(5, min(int(os.environ.get("LOCAL_AGENT_POLL_SECONDS", "10")), 30))
    backoff = interval
    next_update_check = time.monotonic()
    last_seen = state.get("last_task_id")
    last_sha = state.get("manifest_sha")
    print(f"Polling private GitHub mailbox every {interval}s. Press Ctrl+C to stop.")
    print("Local Studio policy controls unattended tasks; unreviewed code patches are NEVER auto-approved.")
    print("Run Blender integration tests on the Windows computer before production use.")

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
                        delivery_status = _task_delivery_status(
                            task.task_id, result_outbox.pending_task_ids()
                        )
                        state = _remember_manifest(
                            state, last_seen, last_sha, status=delivery_status
                        )
                        _save_state(state)
                        if delivery_status == "pending_delivery":
                            print(
                                f"Task {task.task_id} finished, but result delivery is pending; "
                                "the task will not be rerun while its result is retried."
                            )
                    elif decision == "same":
                        record = state.get("processed_tasks", {}).get(task.task_id, {})
                        if isinstance(record, dict) and record.get("status") == "pending_delivery":
                            if task.task_id in result_outbox.pending_task_ids():
                                print(
                                    f"Task {task.task_id} result is still awaiting delivery; "
                                    "preserving the result and not rerunning the task."
                                )
                            else:
                                state = _remember_manifest(
                                    state, task.task_id, manifest_sha, status="processed"
                                )
                                _save_state(state)
                                print(f"Task {task.task_id} result delivery confirmed; marked processed.")
                        elif isinstance(record, dict) and record.get("status") == "in_progress":
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
                        # Preserve the original queue/results/<task_id>.json. Its
                        # immutable contents must NEVER be overwritten by an
                        # attacker-controlled replacement manifest with the same ID.
                        incident_id = _manifest_collision_result_id(task.task_id, manifest_sha)
                        try:
                            _publish_result_durable(client, incident_id, {
                                "task_id": task.task_id,
                                "incident_id": incident_id,
                                "status": "rejected",
                                "reason": "task_id_reused_with_different_manifest",
                            })
                        except QueueTransportError:
                            # The incident is already persisted in the local
                            # outbox; the next poll will retry publication.
                            print(f"Rejected task-ID reuse for {task.task_id}; incident delivery queued.")
                        state = _remember_manifest(state, task.task_id, manifest_sha, rejected=True)
                        _save_state(state)
                        last_sha = manifest_sha
                state = _poll_repair_once(client, state)
                if time.monotonic() >= next_update_check:
                    next_update_check = time.monotonic() + 90  # Avoid extra GitHub API rate-limit load.
                    try:
                        if get_opt_in()["enabled"]:
                            updated = process_pending(
                                client,
                                publish=lambda update_id, result: _publish_result_durable(client, update_id, result),
                            )
                            if updated and updated.get("restart_needed"):
                                print("Trusted update applied and tested; restarting local mailbox agent.")
                                return 75
                    except TrustedUpdateError as exc:
                        print(f"Trusted update safely refused: {exc}")
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


def _supervisor_restart_delay(failures: int, runtime_seconds: float) -> float:
    """Fast crash recovery, with bounded backoff for persistent start failures."""
    return 2.0 if runtime_seconds >= 10 else min(60.0, float(2 ** min(failures + 1, 5)))


def supervise_windows() -> int:
    """Maintain Studio and the private mailbox worker for the signed-in user.

    This process is not an elevated Windows service. It registers a per-user
    login start and (best effort) a one-minute scheduled recovery trigger.
    Worker status is checked every two seconds; a trusted code update (75)
    restarts BOTH services. All Blender rendering remains local.
    """
    if os.name != "nt":
        return main()
    import msvcrt
    import winreg
    import webbrowser
    import urllib.request

    state_dir = _ensure_agent_dir()
    lock_path = state_dir / "octava_supervisor.lock"
    if lock_path.is_symlink():
        raise RuntimeError("Unsafe supervisor lock file")
    lock_stream = lock_path.open("r+b" if lock_path.exists() else "w+b")
    if lock_path.stat().st_size == 0:
        lock_stream.write(b"1")
        lock_stream.flush()
    lock_stream.seek(0)
    try:
        msvcrt.locking(lock_stream.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        # Another supervisor owns the user session. Scheduled recovery task
        # can start each minute without creating duplicate Studio processes.
        lock_stream.close()
        return 0

    root = ROOT.resolve()
    launcher = root / "run_github_mailbox_agent.bat"
    if not launcher.is_file():
        raise RuntimeError("Mailbox supervisor launcher missing")
    os.environ.setdefault("LOCAL_AGENT_GITHUB_REPO", "bjiow131/local-agent-mailbox")
    os.environ.setdefault("LOCAL_AGENT_GITHUB_REF", "main")
    os.environ.setdefault("LOCAL_AGENT_ENABLE_GITHUB_MAILBOX", "1")
    os.environ.setdefault("LOCAL_AGENT_WORKSPACE", str(root.parent / "AI-Agent-Workspace"))

    events_file = state_dir / "octava_supervisor.log"
    port = int(os.environ.get("LOCAL_AGENT_STUDIO_PORT", "55313"))
    if not 1024 <= port <= 65535:
        raise RuntimeError("Invalid Studio supervisor port")
    browser_url = f"http://127.0.0.1:{port}/"
    def log(message: str) -> None:
        # No user prompts, tokens, full command lines or process environment.
        from datetime import datetime, timezone
        item = f"{datetime.now(timezone.utc).isoformat()} {message}\n"
        if sys.stdout is not None:
            print(item.rstrip(), flush=True)
        try:
            if events_file.exists() and events_file.stat().st_size > 400_000:
                events_file.replace(events_file.with_suffix(".old.log"))
            with events_file.open("a", encoding="utf-8") as fh:
                fh.write(item)
        except OSError:
            pass

    # Remove only the legacy startup shortcut created by our old installer.
    # That shortcut starts an interactive Blender helper instead of the
    # supervised Studio + mailbox. Do not remove unrelated user shortcuts.
    legacy_startup = (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows"
                      / "Start Menu" / "Programs" / "Startup" / "Blender Work Agent.lnk")
    if os.environ.get("APPDATA") and legacy_startup.is_file():
        ps_lnk = str(legacy_startup).replace("'", "''")
        ps_target = str(root / "run_blender_agent.bat").replace("'", "''")
        ps = ("$shell=New-Object -ComObject WScript.Shell;"
              "$shortcut=$shell.CreateShortcut('" + ps_lnk + "');"
              "if ($shortcut.TargetPath -ieq '" + ps_target + "') {"
              "Remove-Item -LiteralPath '" + ps_lnk + "' -Force;}")
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False, shell=False,
            )
            if completed.returncode == 0 and not legacy_startup.exists():
                log("Legacy interactive Blender autostart shortcut retired")
        except (OSError, subprocess.TimeoutExpired):
            pass

    # Current-user autostart; never add SYSTEM tasks or request elevation.
    try:
        run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "BlenderOctavaStudioSupervisor", 0, winreg.REG_SZ,
                              f'cmd.exe /d /c ""{launcher}""')
        log("Per-user Windows login autostart registered")
    except OSError:
        log("Windows login autostart registration failed; running for this session")

    # If Windows permits per-user scheduled tasks, also resurrect a crashed
    # supervisor within a minute. The process-wide file lock prevents clones.
    try:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        program = pythonw if pythonw.is_file() else Path(sys.executable)
        trigger = f'"{program}" -m local_agent.poller --supervise'
        completed = subprocess.run(
            ["schtasks.exe", "/Create", "/F", "/SC", "MINUTE", "/MO", "1",
             "/TN", "BlenderOctavaStudioSupervisor", "/TR", trigger],
            cwd=root, timeout=15, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False, shell=False,
        )
        log("Scheduled supervisor recovery installed" if completed.returncode == 0
            else "Scheduled recovery unavailable; login autostart remains")
    except (OSError, subprocess.TimeoutExpired):
        log("Scheduled recovery unavailable; login autostart remains")

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    worker_env = dict(env)
    worker_env["LOCAL_AGENT_MAILBOX_WORKER"] = "1"
    command = {
        "mailbox": [sys.executable, "-m", "local_agent.poller"],
        "studio": [sys.executable, "-m", "local_agent.studio_server",
                   "--workspace", env["LOCAL_AGENT_WORKSPACE"],
                   "--project", "mia_story", "--port", str(port),
                   "--no-browser"],
    }
    processes: dict[str, subprocess.Popen] = {}
    started_at: dict[str, float] = {}
    failures: dict[str, int] = {"mailbox": 0, "studio": 0}
    next_start: dict[str, float] = {"mailbox": 0.0, "studio": 0.0}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def launch(name: str) -> None:
        output = state_dir / ("octava_" + name + ".log")
        try:
            if output.is_file() and output.stat().st_size > 1_000_000:
                output.replace(output.with_suffix(".old.log"))
            with output.open("ab") as stream:
                p = subprocess.Popen(command[name], cwd=root,
                                     env=worker_env if name == "mailbox" else env,
                                     stdin=subprocess.DEVNULL, stdout=stream,
                                     stderr=subprocess.STDOUT, creationflags=flags,
                                     shell=False, close_fds=True)
            processes[name] = p
            started_at[name] = time.monotonic()
            log(f"Started {name} service pid={p.pid}")
        except OSError as exc:
            failures[name] += 1
            next_start[name] = time.monotonic() + min(60, 2 ** min(failures[name] + 1, 5))
            log(f"Failed to start {name}: {type(exc).__name__}")

    def stop(name: str) -> None:
        p = processes.pop(name, None)
        if p is None or p.poll() is not None:
            return
        try:
            p.terminate()
            p.wait(timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            try:
                p.kill()
                p.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def studio_render_active() -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/studio-latest", timeout=2) as response:
                current = json.load(response)
            job = current.get("job") or {}
            return job.get("state") in ("queued", "running")
        except (OSError, ValueError, TypeError, KeyError):
            return False

    try:
        for name in command:
            launch(name)
        # Stable port lets the existing browser tab reconnect after a restart.
        webbrowser.open(browser_url)
        log("Studio and mailbox supervisor active; worker heartbeat every 2s")
        while True:
            time.sleep(2)
            now = time.monotonic()
            for name in command:
                p = processes.get(name)
                if p is not None and p.poll() is not None:
                    code = p.returncode
                    runtime = now - started_at.get(name, now)
                    processes.pop(name, None)
                    if name == "mailbox" and code == 75:
                        log("Trusted update installed; controlled restart of Studio + mailbox")
                        # Avoid terminating an active video render mid-export.
                        render_wait_deadline = time.monotonic() + 600
                        while studio_render_active() and time.monotonic() < render_wait_deadline:
                            time.sleep(3)
                        stop("studio")
                        failures = {"mailbox": 0, "studio": 0}
                        next_start = {"mailbox": 0.0, "studio": 0.0}
                        continue
                    failures[name] = 0 if runtime >= 10 else failures[name] + 1
                    next_start[name] = now + _supervisor_restart_delay(failures[name], runtime)
                    log(f"{name} exited code={code}; auto-restarting")
                if name not in processes and now >= next_start[name]:
                    launch(name)
    except KeyboardInterrupt:
        log("Supervisor stopped on local keyboard request")
        return 0
    finally:
        stop("studio")
        stop("mailbox")
        try:
            lock_stream.seek(0)
            msvcrt.locking(lock_stream.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        lock_stream.close()

if __name__ == "__main__":
    if "--supervise" in sys.argv[1:] or (os.name == "nt" and os.environ.get("LOCAL_AGENT_MAILBOX_WORKER") != "1"):
        raise SystemExit(supervise_windows())
    raise SystemExit(main())
