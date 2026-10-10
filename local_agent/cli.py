"""Safe starter CLI for local diagnostics.

No network listener, background polling, remote execution, or upload is enabled.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from typing import Any

from local_agent.reporting import redact_text, write_report

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / ".local_agent" / "reports"
DEFAULT_LOG_DIRS = (ROOT / ".local_agent" / "logs", ROOT / "logs", ROOT / ".logs", ROOT / "output" / "logs")


def _tool_version(command: list[str]) -> dict[str, Any]:
    exe = shutil.which(command[0])
    if not exe:
        return {"available": False}
    try:
        proc = subprocess.run(
            [exe, *command[1:]], capture_output=True, text=True,
            timeout=5, check=False, shell=False,
        )
        output = (proc.stdout or proc.stderr).strip().splitlines()
        return {
            "available": True,
            "return_code": proc.returncode,
            "version": redact_text(output[0][:240]) if output else "version output unavailable",
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": True, "error": redact_text(type(exc).__name__)}


def doctor() -> dict[str, Any]:
    """Collect minimal local prerequisites without reading environment secrets."""
    return {
        "python": {"version": sys.version.split()[0], "executable_present": True},
        "platform": sys.platform,
        "tools": {
            "git": _tool_version(["git", "--version"]),
            "ffmpeg": _tool_version(["ffmpeg", "-version"]),
            "ffprobe": _tool_version(["ffprobe", "-version"]),
            "nvidia_smi": _tool_version(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"]),
        },
        "pytest_installed": importlib.util.find_spec("pytest") is not None,
        "project_root_exists": ROOT.is_dir(),
        "network_listener_created": False,
        "remote_execution_enabled": False,
    }



def preflight() -> dict[str, Any]:
    """Check local readiness without contacting GitHub or starting a render."""
    import tempfile
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    workspace_check: dict[str, Any] = {"configured": bool(workspace_value), "exists": False, "writable": False}
    disk_free_bytes = None
    if workspace_value:
        try:
            workspace = Path(workspace_value).expanduser().resolve()
            workspace_check["path"] = str(workspace)
            workspace_check["exists"] = workspace.is_dir()
            if workspace.is_dir():
                disk_free_bytes = shutil.disk_usage(workspace).free
                try:
                    with tempfile.NamedTemporaryFile(prefix=".agent-preflight-", dir=workspace, delete=True):
                        workspace_check["writable"] = True
                except OSError:
                    workspace_check["writable"] = False
        except OSError as exc:
            workspace_check["error_type"] = type(exc).__name__
    blender_value = os.environ.get("BLENDER_EXECUTABLE", "").strip()
    blender_path = Path(blender_value).expanduser() if blender_value else None
    if blender_path is None:
        found = shutil.which("blender")
        blender_path = Path(found) if found else None
    blender_check: dict[str, Any] = {"configured": blender_path is not None, "available": False}
    if blender_path is not None:
        blender_check["path"] = str(blender_path)
        if blender_path.is_file():
            try:
                proc = subprocess.run([str(blender_path), "--version"], capture_output=True, text=True,
                                      timeout=10, check=False, shell=False)
                lines = (proc.stdout or proc.stderr).strip().splitlines()
                blender_check.update({"available": proc.returncode == 0, "return_code": proc.returncode,
                                      "version": redact_text(lines[0][:240]) if lines else "version output unavailable"})
            except (OSError, subprocess.TimeoutExpired) as exc:
                blender_check["error_type"] = type(exc).__name__
        else:
            blender_check["error"] = "configured_executable_not_found"
    try:
        from local_agent.github_queue import QueueConfig
        config = QueueConfig.from_environment()
        mailbox = {"configured": True, "repository": config.repository, "ref": config.ref,
                   "manifest_path": config.manifest_path, "token_value_reported": False}
    except Exception as exc:
        mailbox = {"configured": False, "configuration_error_type": type(exc).__name__}
    checks = {
        "python_311_plus": sys.version_info >= (3, 11),
        "workspace_ready": workspace_check.get("exists") is True and workspace_check.get("writable") is True,
        "mailbox_configured": mailbox.get("configured") is True,
        "blender_available": blender_check.get("available") is True,
    }
    return {
        "status": "ready" if all(checks.values()) else "needs_setup",
        "checks": checks, "python": {"version": sys.version.split()[0]},
        "workspace": workspace_check, "disk_free_bytes": disk_free_bytes,
        "mailbox": mailbox, "blender": blender_check,
        "git": _tool_version(["git", "--version"]),
        "ffmpeg": _tool_version(["ffmpeg", "-version"]),
        "ffprobe": _tool_version(["ffprobe", "-version"]),
        "nvidia_smi": _tool_version(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]),
        "network_request_performed": False, "blender_scene_created": False,
        "render_started": False, "secret_values_returned": False,
    }


def status() -> dict[str, Any]:
    """Check only the documented loopback app port; do not scan the network."""
    host, port = "127.0.0.1", 8765
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        connected = sock.connect_ex((host, port)) == 0
    finally:
        sock.close()
    return {
        "app_address": f"http://{host}:{port}",
        "port": port,
        "reachable_on_loopback": connected,
        "network_scan_performed": False,
    }


def tail_logs(limit: int = 200) -> dict[str, Any]:
    """Return a small redacted tail from known local log folders only."""
    found: list[dict[str, Any]] = []
    for folder in DEFAULT_LOG_DIRS:
        if not folder.is_dir():
            continue
        candidates = sorted(
            (p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in {".log", ".txt"}),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:5]
        for path in candidates:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
                found.append({
                    "file": path.name,
                    "lines": [redact_text(line[:2_000]) for line in lines],
                })
            except OSError as exc:
                found.append({"file": path.name, "error": type(exc).__name__})
    return {"files_found": len(found), "logs": found, "upload_performed": False}


def run_tests() -> dict[str, Any]:
    """Run only the repository's standard pytest suite, with no user-supplied command."""
    if importlib.util.find_spec("pytest") is None:
        return {"status": "blocked", "reason": "pytest is not installed"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=ROOT, capture_output=True, text=True, timeout=900,
            check=False, shell=False,
        )
        return {
            "status": "passed" if proc.returncode == 0 else "failed",
            "return_code": proc.returncode,
            "stdout_tail": [redact_text(x[:2_000]) for x in proc.stdout.splitlines()[-120:]],
            "stderr_tail": [redact_text(x[:2_000]) for x in proc.stderr.splitlines()[-120:]],
            "command_allowlisted": True,
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "timeout_seconds": 900}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description="Local-first AI Studio diagnostic agent")
    parser.add_argument("operation", choices=("doctor", "preflight", "status", "logs", "test", "face-rig-check", "character-passport"))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--log-lines", type=int, default=200)
    parser.add_argument("--project", help="Local project folder name for face-rig-check")
    parser.add_argument("--blend-file", help="Optional .blend filename inside the project folder")
    parser.add_argument("--character", help="Character ID for character-passport")
    args = parser.parse_args()

    if args.operation == "doctor":
        details = doctor()
    elif args.operation == "preflight":
        details = preflight()
    elif args.operation == "status":
        details = status()
    elif args.operation == "logs":
        details = tail_logs(max(1, min(args.log_lines, 500)))
    elif args.operation == "face-rig-check":
        if not args.project:
            details = {"status": "blocked", "reason": "face_rig_check_requires_project_name"}
        else:
            from local_agent.blender_face_rig_check import check_face_rig
            details = check_face_rig(args.project, args.blend_file)
    elif args.operation == "character-passport":
        if not args.project or not args.character:
            details = {"status": "blocked", "reason": "character_passport_requires_project_and_character"}
        else:
            from local_agent.character_passport import create_or_update_passport
            details = create_or_update_passport(args.project, args.character, args.blend_file)
    else:
        details = run_tests()

    status_value = str(details.get("status", "collected"))
    try:
        report_path = write_report(args.report_dir, kind=args.operation, status=status_value, details=details)
    except OSError as exc:
        report_path = None
        details["report_write_error"] = type(exc).__name__

    print(json.dumps({
        "operation": args.operation,
        "result": details,
        "report_path": str(report_path) if report_path else None,
        "note": "Report remains local. No upload or remote control is enabled.",
    }, ensure_ascii=False, indent=2))
    return 0 if status_value not in {"failed", "error", "timeout", "blocked", "needs_setup"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
