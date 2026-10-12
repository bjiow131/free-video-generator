"""Local-only control files for a narrowly allowlisted Studio restart."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
_STATUS_NAME = ".studio_server.json"
_REQUEST_NAME = ".studio_restart_request.json"


class RestartControlError(RuntimeError):
    """A Studio restart request could not be created or consumed safely."""


def _safe_project_root(project_root: str | Path) -> Path:
    candidate = Path(project_root).expanduser()
    if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
        raise RestartControlError("Studio project root must not be a symlink or junction")
    try:
        root = candidate.resolve(strict=True)
    except OSError as exc:
        raise RestartControlError("Studio project root is unavailable") from exc
    if not root.is_dir():
        raise RestartControlError("Studio project root is not a directory")
    return root


def _safe_control_path(root: Path, name: str) -> Path:
    path = root / name
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise RestartControlError("Studio control path must not be a symlink or junction")
    return path


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".studio-control-", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise RestartControlError("Studio control path became a symlink")
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def write_server_status(project_root: str | Path, pid: int, port: int) -> Path:
    """Publish the loopback Studio PID and port for the fixed restart controller."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        raise RestartControlError("Invalid Studio process ID")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise RestartControlError("Invalid Studio port")
    root = _safe_project_root(project_root)
    path = _safe_control_path(root, _STATUS_NAME)
    _atomic_json(path, {
        "schema_version": 1,
        "pid": pid,
        "port": port,
        "host": "127.0.0.1",
        "started_at": datetime.now(timezone.utc).isoformat(),
    })
    return path


def clear_server_status(project_root: str | Path, pid: int) -> None:
    """Remove this process's status file without disturbing a replacement server."""
    try:
        root = _safe_project_root(project_root)
        path = _safe_control_path(root, _STATUS_NAME)
        if not path.is_file():
            return
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get("pid") == pid:
            path.unlink()
    except (OSError, ValueError, RestartControlError):
        return


def _read_status(root: Path) -> dict[str, Any] | None:
    path = _safe_control_path(root, _STATUS_NAME)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    if (not isinstance(value, dict) or set(value) != {
        "schema_version", "pid", "port", "host", "started_at"
    } or value.get("schema_version") != 1
            or isinstance(value.get("pid"), bool) or not isinstance(value.get("pid"), int)
            or value["pid"] < 1
            or isinstance(value.get("port"), bool) or not isinstance(value.get("port"), int)
            or not 1 <= value["port"] <= 65535
            or value.get("host") != "127.0.0.1"):
        return None
    return value


def _studio_is_alive(status: dict[str, Any]) -> bool:
    """Confirm the recorded local process endpoint before writing a restart signal."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{status['port']}/api/health",
        headers={"Host": f"127.0.0.1:{status['port']}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=1.0) as response:
            body = json.loads(response.read(4096).decode("utf-8"))
        return response.status == 200 and body == {"status": "ok", "offline": True}
    except (OSError, ValueError, UnicodeError, urllib.error.URLError):
        return False


def peek_restart_request(project_root: str | Path) -> dict[str, Any] | None:
    """Read a pending fixed restart signal; malformed or stale signals are discarded."""
    root = _safe_project_root(project_root)
    path = _safe_control_path(root, _REQUEST_NAME)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        valid = isinstance(value, dict) and set(value) == {
            "schema_version", "operation", "task_id", "created_at"
        }
        if valid:
            created = datetime.fromisoformat(str(value.get("created_at", "")).replace("Z", "+00:00"))
            age_seconds = (datetime.now(timezone.utc) - created).total_seconds()
            valid = (
                value.get("schema_version") == 1
                and value.get("operation") == "restart_agent"
                and isinstance(value.get("task_id"), str)
                and bool(_TASK_ID.fullmatch(value["task_id"]))
                and created.tzinfo is not None
                and 0 <= age_seconds <= 3600
            )
    except (OSError, ValueError, TypeError, UnicodeError):
        valid = False
        value = None
    if not valid:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return value


def clear_restart_request(project_root: str | Path, task_id: str) -> None:
    """Remove only the pending request matching the task that was observed."""
    try:
        root = _safe_project_root(project_root)
        path = _safe_control_path(root, _REQUEST_NAME)
        value = peek_restart_request(root)
        if value is not None and value.get("task_id") == task_id:
            path.unlink(missing_ok=True)
    except (OSError, RestartControlError):
        return


def _launch_studio(launcher_path: str | Path) -> None:
    """Open the fixed local batch entry point when Studio is not running."""
    launcher = Path(launcher_path).expanduser()
    if launcher.is_symlink() or getattr(launcher, "is_junction", lambda: False)():
        raise RestartControlError("Studio launcher must not be a symlink or junction")
    try:
        actual = launcher.resolve(strict=True)
    except OSError as exc:
        raise RestartControlError("Studio launcher is missing") from exc
    if not actual.is_file() or actual.suffix.lower() != ".bat":
        raise RestartControlError("Studio launcher must be the approved .bat entry point")
    if os.name != "nt" or not hasattr(os, "startfile"):
        raise RestartControlError("Studio is not running and automatic Windows launch is unavailable")
    os.startfile(str(actual))  # type: ignore[attr-defined]


def request_agent_restart(
    project_root: str | Path, task_id: str, launcher_path: str | Path
) -> dict[str, Any]:
    """Restart Studio if live, or reopen it with its official local launcher."""
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise RestartControlError("Invalid restart task ID")
    root = _safe_project_root(project_root)
    status = _read_status(root)
    if status is None or not _studio_is_alive(status):
        _launch_studio(launcher_path)
        return {
            "status": "completed",
            "action": "studio_opened",
            "browser_will_open": True,
            "studio_pid": None,
        }

    path = _safe_control_path(root, _REQUEST_NAME)
    request = {
        "schema_version": 1,
        "operation": "restart_agent",
        "task_id": task_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(request, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise RestartControlError("A Studio restart is already pending") from exc
    return {
        "status": "completed",
        "action": "studio_restart_scheduled",
        "browser_will_open": True,
        "studio_pid": status["pid"],
    }
