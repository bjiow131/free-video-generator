"""Locally authorized unattended GitHub mailbox operations.

Opt-in is set through loopback Studio UI, NEVER from an incoming GitHub task.
An enabled policy auto-runs selected bounded handlers without the console YES.
Unreviewed patches, arbitrary commands and repairs are never auto-approved.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
POLICY_FILE = _ROOT / '.local_agent' / 'mailbox_policy.json'
_LOCK = threading.RLock()
_POLICY_FIELDS = {'enabled', 'allow_octava', 'allow_blender', 'allow_tests', 'allow_asset_sync'}
_LEGACY_POLICY_FIELDS = {'enabled', 'allow_octava', 'allow_blender', 'allow_tests'}
READ_ONLY_OPERATIONS = frozenset({
    'doctor', 'preflight', 'status', 'blender_preflight',
    'blender_inspect_mia_project', 'blender_knowledge_search',
    'scan_project_assets', 'compile_story_plan',
})
BLENDER_OPERATIONS = frozenset({
    'save_story_plan', 'blender_forest_preview',
    'blender_mia_blockout', 'blender_mia_skeleton',
    'blender_mia_spring_rig_transfer', 'blender_source_review', 'blender_mia_source_adapt', 'blender_mia_source_recover', 'blender_mia_source_neutral', 'blender_mia_source_details', 'blender_mia_source_polish', 'export_mia_scene_review',
    'mia_model_review', 'mia_astra_review', 'mia_astra_pass_one', 'mia_identity_pass_two', 'mia_hair_identity_pass_three', 'mia_3d_reconstruction_preflight', 'mia_astra_autoloop_100', 'mia_astra_autoloop_100_v2', 'mia_astra_single_maxfix', 'mia_2p5d_prototype',
})
# Tests execute checked-out local project code. Require a separate checkbox.
TEST_OPERATIONS = frozenset({'test', 'trusted_update_diagnostics'})
# Never allow unattended: apply_patch, open GUI, start/stop, backup, logs,
# remotely provided code, unreviewed repair packages, or unknown operations.


class MailboxPolicyError(ValueError):
    pass


def default_policy() -> dict[str, bool]:
    return {'enabled': False, 'allow_octava': False, 'allow_blender': False,
            'allow_tests': False, 'allow_asset_sync': False}


def _validate(data: Any) -> dict[str, bool]:
    if isinstance(data, dict) and set(data) == _LEGACY_POLICY_FIELDS:
        # Add the new permission as disabled when reading older local settings.
        data = {**data, 'allow_asset_sync': False}
    if not isinstance(data, dict) or set(data) != _POLICY_FIELDS:
        raise MailboxPolicyError('Некорректные поля политики автономного режима')
    if any(type(data[name]) is not bool for name in _POLICY_FIELDS):
        raise MailboxPolicyError('Параметры автономного режима должны быть true/false')
    return {name: data[name] for name in ('enabled', 'allow_octava', 'allow_blender', 'allow_tests', 'allow_asset_sync')}


def _safe_directory() -> Path:
    directory = POLICY_FILE.parent
    if directory.is_symlink() or getattr(directory, 'is_junction', lambda: False)():
        raise MailboxPolicyError('Папка политики не должна быть ссылкой или junction')
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve().is_relative_to(_ROOT.resolve()):
        raise MailboxPolicyError('Папка политики выходит за пределы приложения')
    return directory


def _safe_file(path: Path) -> None:
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
        raise MailboxPolicyError('Файл политики не должен быть ссылкой или junction')


def load_policy() -> dict[str, bool]:
    with _LOCK:
        _safe_directory()
        _safe_file(POLICY_FILE)
        try:
            blob = POLICY_FILE.read_bytes()
        except FileNotFoundError:
            return default_policy()
        except OSError as exc:
            raise MailboxPolicyError('Не удалось прочесть политику') from exc
        if len(blob) > 1024:
            raise MailboxPolicyError('Политика слишком большая')
        try:
            return _validate(json.loads(blob.decode('utf-8')))
        except (UnicodeError, ValueError, TypeError) as exc:
            raise MailboxPolicyError('Повреждена локальная политика; автономный режим заблокирован') from exc


def _atomic_write(path: Path, content: bytes) -> None:
    directory = _safe_directory()
    _safe_file(path)
    name = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.mailbox-policy-', suffix='.tmp',
                                         dir=directory, delete=False) as stream:
            name = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    except OSError as exc:
        raise MailboxPolicyError('Не удалось сохранить локальную политику') from exc
    finally:
        if name is not None:
            try:
                Path(name).unlink(missing_ok=True)
            except OSError:
                pass


def save_policy(value: dict[str, bool]) -> dict[str, bool]:
    data = _validate(value)
    with _LOCK:
        _atomic_write(POLICY_FILE, (json.dumps(data, sort_keys=True) + '\n').encode('utf-8'))
    return data


def is_auto_authorized(operation: str, policy: dict[str, bool] | None = None) -> bool:
    p = load_policy() if policy is None else _validate(policy)
    if not p['enabled']:
        return False
    if operation in READ_ONLY_OPERATIONS:
        return True
    if operation == 'sync_approved_assets':
        return p['allow_asset_sync']
    if operation in BLENDER_OPERATIONS:
        return p['allow_blender']
    if operation in TEST_OPERATIONS:
        return p['allow_tests']
    if operation == 'octava_advice':
        return p['allow_octava']
    return False



# Both the Studio UI and GitHub updater use this same opt-in file.
# Kept here so the offline Studio process never imports requests/GitHub.
_TRUSTED_UPDATES_OPT_IN = _ROOT / '.local_agent' / 'trusted_updates_enabled.json'


def get_trusted_update_opt_in() -> dict[str, bool]:
    """Read explicit local update consent without loading network dependencies."""
    with _LOCK:
        _safe_directory()
        _safe_file(_TRUSTED_UPDATES_OPT_IN)
        try:
            raw = _TRUSTED_UPDATES_OPT_IN.read_bytes()
        except FileNotFoundError:
            return {'enabled': False}
        except OSError as exc:
            raise MailboxPolicyError('Не удалось прочесть разрешение на обновления') from exc
        if len(raw) > 120:
            raise MailboxPolicyError('Повреждено разрешение на обновления')
        try:
            data = json.loads(raw)
        except (UnicodeError, ValueError, TypeError) as exc:
            raise MailboxPolicyError('Повреждено разрешение на обновления') from exc
        if not isinstance(data, dict) or set(data) != {'enabled'} or type(data['enabled']) is not bool:
            raise MailboxPolicyError('Повреждено разрешение на обновления')
        return data


def set_trusted_update_opt_in(value: dict[str, bool]) -> dict[str, bool]:
    """Save Studio update consent in the file used by trusted_updates.get_opt_in."""
    if not isinstance(value, dict) or set(value) != {'enabled'} or type(value['enabled']) is not bool:
        raise MailboxPolicyError('Ожидается enabled: true/false')
    with _LOCK:
        _atomic_write(_TRUSTED_UPDATES_OPT_IN,
                      (json.dumps(value, sort_keys=True) + '\n').encode('utf-8'))
    return value

def reserve_octava_call(now=None) -> None:
    """Backward-compatible no-op: no ChatGPT-side daily OctavAPI call limit.

    Authorization remains governed by the locally saved allow_octava policy.
    The third-party provider may independently charge for tokens or impose
    its own limits. Kept as a no-op for older poller/test integrations.
    """
    return None


# Shared with the Telegram sender in Studio and the Windows mailbox worker.
# Default is enabled to preserve alerts for already paired bots on upgrade.
TELEGRAM_NOTIFICATIONS = _ROOT / ".local_agent" / "telegram_notifications.json"


def _validate_telegram_notifications(value: Any) -> dict[str, bool]:
    if (not isinstance(value, dict) or set(value) != {"enabled"}
            or type(value["enabled"]) is not bool):
        raise MailboxPolicyError("Ожидается только enabled: true/false")
    return {"enabled": value["enabled"]}


def load_telegram_notifications() -> dict[str, bool]:
    with _LOCK:
        _safe_directory()
        _safe_file(TELEGRAM_NOTIFICATIONS)
        try:
            data = TELEGRAM_NOTIFICATIONS.read_bytes()
        except FileNotFoundError:
            return {"enabled": True}
        except OSError as exc:
            raise MailboxPolicyError("Не удалось прочитать настройки уведомлений") from exc
        if len(data) > 128:
            raise MailboxPolicyError("Некорректные настройки уведомлений")
        try:
            return _validate_telegram_notifications(json.loads(data.decode("utf-8")))
        except (UnicodeError, ValueError, TypeError) as exc:
            raise MailboxPolicyError("Повреждены настройки уведомлений") from exc


def save_telegram_notifications(value: dict) -> dict[str, bool]:
    checked = _validate_telegram_notifications(value)
    with _LOCK:
        _atomic_write(TELEGRAM_NOTIFICATIONS, (json.dumps(checked) + "\n").encode("utf-8"))
    return checked


def telegram_notifications_enabled() -> bool:
    """Stop all outgoing alerts if settings are damaged or notifications disabled."""
    try:
        return load_telegram_notifications()["enabled"]
    except MailboxPolicyError:
        return False


# Durable local controls shared across Studio, Telegram supervisor and mailbox worker.
# These files contain no credentials or remote-provided shell commands.
RUNTIME_CONTROL_FILE = _ROOT / ".local_agent" / "runtime_control.json"
_MAX_RESTART_ID = 2**53 - 1


def _validate_runtime_control(value: Any) -> dict[str, Any]:
    expected = {"paused", "restart_requested", "restart_acknowledged"}
    if not isinstance(value, dict) or set(value) != expected:
        raise MailboxPolicyError("Некорректные параметры управления агентом")
    if type(value["paused"]) is not bool:
        raise MailboxPolicyError("Некорректный параметр паузы")
    requested, acknowledged = value["restart_requested"], value["restart_acknowledged"]
    if (type(requested) is not int or type(acknowledged) is not int or
            not (0 <= acknowledged <= requested <= _MAX_RESTART_ID)):
        raise MailboxPolicyError("Некорректное состояние перезапуска")
    return {"paused": value["paused"], "restart_requested": requested,
            "restart_acknowledged": acknowledged}


def load_runtime_control() -> dict[str, Any]:
    with _LOCK:
        _safe_directory()
        _safe_file(RUNTIME_CONTROL_FILE)
        try:
            raw = RUNTIME_CONTROL_FILE.read_bytes()
        except FileNotFoundError:
            return {"paused": False, "restart_requested": 0, "restart_acknowledged": 0}
        except OSError as exc:
            raise MailboxPolicyError("Не удалось прочитать состояние агента") from exc
        if len(raw) > 256:
            raise MailboxPolicyError("Состояние агента превышает допустимый размер")
        try:
            return _validate_runtime_control(json.loads(raw.decode("utf-8")))
        except (ValueError, TypeError, UnicodeError) as exc:
            raise MailboxPolicyError("Повреждено состояние агента") from exc


def _save_runtime(value: dict[str, Any]) -> dict[str, Any]:
    validated = _validate_runtime_control(value)
    _atomic_write(RUNTIME_CONTROL_FILE,
                  (json.dumps(validated, sort_keys=True) + "\n").encode("utf-8"))
    return validated


def set_runtime_pause(value: dict) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"paused"} or type(value["paused"]) is not bool:
        raise MailboxPolicyError("Ожидается paused: true/false")
    with _LOCK:
        return _save_runtime({**load_runtime_control(), "paused": value["paused"]})


def request_runtime_restart(value: dict) -> dict[str, Any]:
    if value != {}:
        raise MailboxPolicyError("Запрос на перезапуск не должен содержать параметров")
    with _LOCK:
        current = load_runtime_control()
        # Coalesce multiple outstanding clicks/commands into one controlled restart.
        if current["restart_requested"] == current["restart_acknowledged"]:
            if current["restart_requested"] >= _MAX_RESTART_ID:
                raise MailboxPolicyError("Исчерпаны идентификаторы перезапуска")
            current["restart_requested"] += 1
            current = _save_runtime(current)
        return {"restart_pending": True}


def acknowledge_runtime_restart() -> bool:
    """Return True only if a new restart request was consumed."""
    with _LOCK:
        current = load_runtime_control()
        if current["restart_requested"] == current["restart_acknowledged"]:
            return False
        _save_runtime({**current, "restart_acknowledged": current["restart_requested"]})
        return True


# === Durable OctavAPI project memory: embedded in pre-authorized module ===
# The trusted Windows updater can update mailbox_policy.py, but cannot install
# arbitrary new modules. Keeping this implementation here preserves its allowlist.

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time

PROJECT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}\Z")
STEP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SECRET = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{16,}|github_pat_[A-Za-z0-9_]{12,}"
    r"|gh[pousr]_[A-Za-z0-9]{12,}|Bearer\s+\S+"
    r"|(?:api[_-]?key|token|пароль|password|authorization)\s*[:=]\s*\S+)"
)
_PROJECT_MEMORY_LOCK = threading.RLock()
MAX_FILE = 64_000
MAX_HISTORY = 8
MAX_STEPS = 40


class MemoryErrorSafe(ValueError):
    """No path/secret details in public errors."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(value: str, limit: int) -> str:
    if not isinstance(value, str):
        raise MemoryErrorSafe("Project memory only accepts text")
    value = value.strip()
    if _SECRET.search(value):
        raise MemoryErrorSafe("Project checkpoint appears to contain a secret")
    if len(value) > limit:
        raise MemoryErrorSafe("Project checkpoint exceeds text limit")
    if any(ord(c) < 32 and c not in "\n\t\r" for c in value):
        raise MemoryErrorSafe("Invalid project checkpoint text")
    return value


class OctavaProjectMemory:
    def __init__(self, workspace: str | Path, project_id: str):
        if not isinstance(project_id, str) or not PROJECT_ID.fullmatch(project_id):
            raise MemoryErrorSafe("Invalid project_id")
        if not str(workspace).strip():
            raise MemoryErrorSafe("LOCAL_AGENT_WORKSPACE is required for project memory")
        self.project_id = project_id
        self.root = Path(workspace).expanduser().resolve() / ".local_agent" / "ai_project_memory"
        self.path = self.root / (project_id + ".json")

    def _ensure_root(self) -> None:
        # Do not follow a pre-existing attacker-controlled junction/symlink.
        workspace = self.root.parent.parent
        for path in (workspace / ".local_agent", self.root):
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise MemoryErrorSafe("Unsafe project memory directory")
            path.mkdir(exist_ok=True)
        if self.path.is_symlink() or getattr(self.path, "is_junction", lambda: False)():
            raise MemoryErrorSafe("Unsafe project memory file")

    @contextmanager
    def _locked(self):
        with _PROJECT_MEMORY_LOCK:
            self._ensure_root()
            lock = self.root / (self.project_id + ".lock")
            deadline = time.monotonic() + 5
            while True:
                try:
                    lock.mkdir()
                    break
                except FileExistsError:
                    if lock.is_symlink() or getattr(lock, "is_junction", lambda: False)():
                        raise MemoryErrorSafe("Unsafe project memory lock")
                    try:
                        # A crashed process should not lock the session forever.
                        if time.time() - lock.stat().st_mtime > 120:
                            lock.rmdir()
                            continue
                    except OSError:
                        pass
                    if time.monotonic() >= deadline:
                        raise MemoryErrorSafe("Project memory is busy")
                    time.sleep(0.05)
            try:
                yield
            finally:
                try:
                    lock.rmdir()
                except OSError:
                    pass

    def _empty(self) -> dict:
        return {"schema_version": 1, "project_id": self.project_id,
                "revision": 0, "status": "idle", "pending": None,
                "history": [], "steps": [], "updated_at": _now()}

    def _read(self) -> dict:
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_FILE + 1)
        except FileNotFoundError:
            return self._empty()
        except OSError:
            raise MemoryErrorSafe("Cannot read project memory") from None
        if len(raw) > MAX_FILE:
            raise MemoryErrorSafe("Project memory exceeds safe size")
        try:
            data = json.loads(raw.decode("utf-8"))
            if (not isinstance(data, dict)
                or set(data) != {"schema_version", "project_id", "revision", "status",
                                "pending", "history", "steps", "updated_at"}
                or data["schema_version"] != 1 or data["project_id"] != self.project_id
                or type(data["revision"]) is not int or data["revision"] < 0
                or data["status"] not in ("idle", "in_flight", "waiting_for_key", "retry_later")
                or not isinstance(data["history"], list) or len(data["history"]) > MAX_HISTORY
                or not isinstance(data["steps"], list) or len(data["steps"]) > MAX_STEPS
                or any(not isinstance(t, dict) or set(t) != {"prompt", "answer"}
                       or not isinstance(t["prompt"], str) or len(t["prompt"]) > 1600
                       or not isinstance(t["answer"], str) or len(t["answer"]) > 2500
                       or _SECRET.search(t["prompt"]) or _SECRET.search(t["answer"])
                       for t in data["history"])
                or any(not isinstance(t, dict) or set(t) != {"id", "state", "note"}
                       or not isinstance(t["id"], str) or not STEP_ID.fullmatch(t["id"])
                       or t["state"] not in ("completed", "blocked", "failed")
                       or not isinstance(t["note"], str) or len(t["note"]) > 300
                       for t in data["steps"])
                or (data["pending"] is not None and
                    (not isinstance(data["pending"], str) or len(data["pending"]) > 1600))):
                raise ValueError("invalid")
        except (ValueError, TypeError, UnicodeError):
            raise MemoryErrorSafe("Project memory is invalid; preserving file") from None
        return data

    def _write(self, data: dict) -> None:
        data["updated_at"] = _now()
        data["revision"] += 1
        payload = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(payload) > MAX_FILE:
            raise MemoryErrorSafe("Project memory exceeds safe size")
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.root,
                                             prefix=".checkpoint-", suffix=".tmp",
                                             delete=False) as output:
                tmp = Path(output.name)
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            if os.name != "nt":
                os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except OSError:
            raise MemoryErrorSafe("Could not persist project checkpoint") from None
        finally:
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    def _append_journal(self, entry: dict) -> None:
        """Append accepted events to a durable local archive without an 8-turn cap.

        The compact snapshot retains only recent context for the API model.
        The journal is archival; it never stores tokens or raw rendering files.
        """
        path = self.root / (self.project_id + ".history.jsonl")
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise MemoryErrorSafe("Unsafe project history path")
        record = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(descriptor, "ab") as stream:
                stream.write(record)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            raise MemoryErrorSafe("Could not archive project progress") from None

    def snapshot(self) -> dict:
        with self._locked():
            return self._read()

    def begin(self, prompt: str | None = None, *, resume: bool = False) -> tuple[str, list[dict]]:
        with self._locked():
            data = self._read()
            if resume:
                if data["pending"] is None:
                    raise MemoryErrorSafe("No pending project request to resume")
                question = _clean(data["pending"], 1600)
            else:
                question = _clean(prompt, 1600)
                if not question:
                    raise MemoryErrorSafe("Empty project request")
                if data["pending"] is not None:
                    raise MemoryErrorSafe("Resume pending project request before starting a new one")
                data["pending"] = question
            data["status"] = "in_flight"
            self._write(data)  # checkpoint BEFORE a potentially billable API call
            return question, list(data["history"])

    def complete(self, prompt: str, answer: str) -> dict:
        with self._locked():
            data = self._read()
            if data["pending"] != prompt:
                raise MemoryErrorSafe("Pending project request changed")
            item = {"prompt": _clean(prompt, 1600), "answer": _clean(answer, 2500)}
            self._append_journal({"event": "answer", "date": _now(), **item})
            data["history"].append(item)
            data["history"] = data["history"][-MAX_HISTORY:]
            data["pending"] = None
            data["status"] = "idle"
            self._write(data)
            return {"project_id": self.project_id, "revision": data["revision"],
                    "history_turns": len(data["history"]), "status": data["status"]}

    def fail(self, reason: str) -> None:
        if reason not in ("waiting_for_key", "retry_later"):
            reason = "retry_later"
        with self._locked():
            data = self._read()
            if data["pending"] is not None:
                data["status"] = reason
                self._write(data)

    def checkpoint_step(self, step_id: str, state: str, note: str = "") -> dict:
        """Persist a verified milestone, independently of the active API key.

        Call ONLY after the agent has checked the actual external side effect.
        """
        if not isinstance(step_id, str) or not STEP_ID.fullmatch(step_id):
            raise MemoryErrorSafe("Invalid milestone id")
        if state not in ("completed", "blocked", "failed"):
            raise MemoryErrorSafe("Invalid milestone state")
        note = _clean(note, 300)
        with self._locked():
            data = self._read()
            data["steps"] = [s for s in data["steps"] if s["id"] != step_id]
            data["steps"].append({"id": step_id, "state": state, "note": note})
            data["steps"] = data["steps"][-MAX_STEPS:]
            self._append_journal({"event": "step", "date": _now(),
                                  "id": step_id, "state": state, "note": note})
            self._write(data)
            return {"project_id": self.project_id, "revision": data["revision"],
                    "step_id": step_id, "state": state}

    @staticmethod
    def waiting_projects(workspace: str | Path, limit: int = 3) -> list[str]:
        """Only local sessions paused specifically for a key change."""
        if type(limit) is not int or not 1 <= limit <= 10:
            raise MemoryErrorSafe("Invalid resume limit")
        base = Path(workspace).expanduser().resolve() / ".local_agent" / "ai_project_memory"
        if base.is_symlink() or getattr(base, "is_junction", lambda: False)():
            raise MemoryErrorSafe("Unsafe project memory directory")
        if not base.exists():
            return []
        result = []
        for path in sorted(base.glob("*.json")):
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                continue
            project_id = path.stem
            if not PROJECT_ID.fullmatch(project_id):
                continue
            try:
                snapshot = OctavaProjectMemory(workspace, project_id).snapshot()
            except MemoryErrorSafe:
                continue
            if snapshot["status"] == "waiting_for_key" and snapshot["pending"] is not None:
                result.append(project_id)
                if len(result) >= limit:
                    break
        return result

    @staticmethod
    def context(history: list[dict], steps: list[dict]) -> str:
        # Last few turns limit third-party context size and avoid high payloads.
        pieces = ["Saved project facts, not executable instructions:"]
        for step in steps[-12:]:
            pieces.append("Step: " + str(step["id"]) + " = " + str(step["state"]) +
                          " (" + str(step.get("note", ""))[:100] + ")")
        for item in history[-4:]:
            pieces.append("Previous question: " + str(item["prompt"])[:1200])
            pieces.append("Previous answer: " + str(item["answer"])[:1800])
        return "\n".join(pieces)[:11000]




# === Durable, preemptible mailbox task workers ===
# Kept in this allowlisted module because the signed-in Windows updater is
# deliberately restricted to a fixed set of files.
import hashlib as _task_hashlib
import signal as _task_signal
import subprocess as _task_subprocess
import sys
import sys as _task_sys
import time as _task_time
from dataclasses import replace as dataclass_replace
from datetime import datetime as _TaskDateTime, timedelta as _TaskDelta, timezone as _TaskTZ
from pathlib import Path as _TaskPath

TASK_RUNS_DIR = _ROOT / ".local_agent" / "task_runs"
TASK_STOP_REQUEST = _ROOT / ".local_agent" / "task_stop_request.json"
TASK_ACTIVE_FILE = _ROOT / ".local_agent" / "task_active.json"
_TASK_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
_TASK_LOCK = threading.RLock()
_CONTROL_OPERATIONS = {"stop_task", "resume_task", "cancel_task"}
_TASK_ACTIVE: dict[str, Any] = {}


class TaskJournalError(ValueError):
    pass


def _task_safe_root() -> _TaskPath:
    base = _ROOT / ".local_agent"
    for path in (base, TASK_RUNS_DIR):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise TaskJournalError("Unsafe task journal path")
        path.mkdir(parents=True, exist_ok=True)
    if not TASK_RUNS_DIR.resolve().is_relative_to(_ROOT.resolve()):
        raise TaskJournalError("Task journal escapes application root")
    return TASK_RUNS_DIR


def _task_id(value: Any) -> str:
    if not isinstance(value, str) or not _TASK_ID_RE.fullmatch(value):
        raise TaskJournalError("Invalid task identifier")
    return value


def _task_atomic_json(path: _TaskPath, value: dict) -> None:
    task_root = _task_safe_root()
    root = task_root.parent
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise TaskJournalError("Unsafe task journal file")
    if not path.resolve().is_relative_to(root.resolve()):
        raise TaskJournalError("Task journal file escapes root")
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(data) > 128_000:
        raise TaskJournalError("Task journal record exceeds size limit")
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=root, prefix=".task-", suffix=".tmp", delete=False) as stream:
            tmp = _TaskPath(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        raise TaskJournalError("Could not persist task journal") from exc
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


class TaskJournal:
    """Durable original inputs, append-only attempts, and compact status."""
    def __init__(self, task_id: str):
        self.task_id = _task_id(task_id)
        self.directory = _task_safe_root() / self.task_id
        if self.directory.is_symlink() or getattr(self.directory, "is_junction", lambda: False)():
            raise TaskJournalError("Unsafe task journal directory")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.input_path = self.directory / "input.json"
        self.state_path = self.directory / "state.json"

    def save_input(self, envelope: dict, *, source_task_id: str | None = None) -> None:
        if not isinstance(envelope, dict) or set(envelope) != {
            "protocol_version", "task_id", "operation", "created_at", "expires_at",
            "requires_local_approval", "arguments",
        }:
            raise TaskJournalError("Invalid task envelope")
        if envelope["task_id"] != self.task_id or envelope["requires_local_approval"] is not True:
            raise TaskJournalError("Task identity or local approval changed")
        if self.input_path.exists():
            prior = self.load_input()["envelope"]
            if prior != envelope:
                raise TaskJournalError("Task ID was reused with different input")
            return
        _task_atomic_json(self.input_path, {"envelope": envelope,
                                             "source_task_id": source_task_id or self.task_id,
                                             "saved_at": _task_now()})

    def load_input(self) -> dict:
        _task_safe_root()
        if self.input_path.is_symlink() or getattr(self.input_path, "is_junction", lambda: False)():
            raise TaskJournalError("Unsafe task input")
        try:
            raw = self.input_path.read_bytes()
            if len(raw) > 128_000:
                raise ValueError("large")
            data = json.loads(raw.decode("utf-8"))
            envelope = data["envelope"]
            if (not isinstance(data, dict) or set(data) != {"envelope", "source_task_id", "saved_at"}
                    or not isinstance(envelope, dict) or envelope.get("task_id") != self.task_id
                    or envelope.get("requires_local_approval") is not True):
                raise ValueError("invalid")
            return data
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            raise TaskJournalError("Saved task input is missing or invalid") from None

    def state(self) -> dict:
        _task_safe_root()
        if self.state_path.is_symlink() or getattr(self.state_path, "is_junction", lambda: False)():
            raise TaskJournalError("Unsafe task state")
        try:
            raw = self.state_path.read_bytes()
            if len(raw) > 64_000:
                raise ValueError("large")
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict) or data.get("task_id") != self.task_id:
                raise ValueError("invalid")
            return data
        except FileNotFoundError:
            return {"task_id": self.task_id, "status": "queued", "attempts": [], "updated_at": _task_now()}
        except (OSError, ValueError, TypeError, UnicodeError):
            raise TaskJournalError("Saved task state is invalid") from None

    def update(self, status: str, **extra: Any) -> dict:
        with _TASK_LOCK:
            state = self.state()
            state["status"] = status
            state["updated_at"] = _task_now()
            for key in ("reason", "attempt", "worker_pid", "result_status", "error_type", "source_task_id"):
                if key in extra and isinstance(extra[key], (str, int, type(None))):
                    state[key] = extra[key]
            _task_atomic_json(self.state_path, state)
            return state

    def add_attempt(self, record: dict) -> None:
        with _TASK_LOCK:
            state = self.state()
            attempts = state.get("attempts", [])
            if not isinstance(attempts, list) or len(attempts) >= 100:
                raise TaskJournalError("Task attempt history is invalid or full")
            attempts.append(record)
            state.update({"status": "running", "attempts": attempts, "updated_at": _task_now()})
            _task_atomic_json(self.state_path, state)

    def finish_attempt(self, attempt: int, status: str, **extra: Any) -> None:
        with _TASK_LOCK:
            state = self.state()
            attempts = state.get("attempts", [])
            if not isinstance(attempts, list) or not 1 <= attempt <= len(attempts):
                raise TaskJournalError("Task attempt is missing")
            record = dict(attempts[attempt - 1])
            record.update({"status": status, "finished_at": _task_now()})
            for key in ("reason", "exit_code", "result_status", "error_type"):
                if key in extra and isinstance(extra[key], (str, int, type(None))):
                    record[key] = extra[key]
            attempts[attempt - 1] = record
            state.update({"status": status, "attempts": attempts, "updated_at": _task_now()})
            _task_atomic_json(self.state_path, state)


def _task_now() -> str:
    return _TaskDateTime.now(_TaskTZ.utc).isoformat(timespec="seconds")


def _task_envelope(task: Any) -> dict:
    return {"protocol_version": task.protocol_version, "task_id": task.task_id,
            "operation": task.operation, "created_at": task.created_at,
            "expires_at": task.expires_at,
            "requires_local_approval": task.requires_local_approval,
            "arguments": task.arguments}


_queue_parse_task_original = None
_poller_run_one_original = None
_poller_telegram_original = None


def install_task_control_parser() -> None:
    """Accept only three typed control envelopes; normalize before strict parse."""
    global _queue_parse_task_original
    from local_agent import github_queue
    if _queue_parse_task_original is not None:
        return
    _queue_parse_task_original = github_queue.parse_task

    def parse(raw: str):
        from local_agent.control_protocol import ProtocolError
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            return _queue_parse_task_original(raw)
        if not isinstance(value, dict) or value.get("operation") not in _CONTROL_OPERATIONS:
            return _queue_parse_task_original(raw)
        operation = value["operation"]
        args = value.get("arguments")
        if value.get("requires_local_approval") is not True:
            raise ProtocolError("Task must require local approval.")
        if operation == "stop_task":
            if args != {}:
                raise ProtocolError("stop_task accepts no arguments.")
        elif (not isinstance(args, dict) or set(args) != {"task_id"}
              or not isinstance(args.get("task_id"), str) or not _TASK_ID_RE.fullmatch(args["task_id"])):
            raise ProtocolError(operation + " requires one valid task_id.")
        normalized = dict(value)
        normalized["operation"] = "status"
        normalized["arguments"] = {}
        task = _queue_parse_task_original(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")))
        return dataclass_replace(task, operation=operation, arguments=args)

    github_queue.parse_task = parse


def _task_read_active() -> dict | None:
    if TASK_ACTIVE_FILE.is_symlink() or getattr(TASK_ACTIVE_FILE, "is_junction", lambda: False)():
        return None
    try:
        data = json.loads(TASK_ACTIVE_FILE.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or set(data) != {"task_id", "pid", "updated_at"}
                or not isinstance(data["task_id"], str) or not _TASK_ID_RE.fullmatch(data["task_id"])
                or type(data["pid"]) is not int or data["pid"] <= 0):
            return None
        stamp = _TaskDateTime.fromisoformat(data["updated_at"])
        if abs((_TaskDateTime.now(_TaskTZ.utc) - stamp).total_seconds()) > 86400:
            return None
        try:
            os.kill(data["pid"], 0)
        except PermissionError:
            pass
        except OSError:
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        return None


def _task_request_stop() -> bool:
    active = _task_read_active()
    if active is None:
        return False
    _task_atomic_json(TASK_STOP_REQUEST, {"task_id": active["task_id"], "requested_at": _task_now()})
    return True


def _task_publish_active(task_id: str, pid: int) -> None:
    _task_atomic_json(TASK_ACTIVE_FILE, {"task_id": task_id, "pid": int(pid), "updated_at": _task_now()})


def _task_clear_active(task_id: str) -> None:
    active = _task_read_active()
    if active is not None and active["task_id"] == task_id:
        try:
            TASK_ACTIVE_FILE.unlink(missing_ok=True)
        except OSError:
            pass


def _task_consume_stop(task_id: str) -> bool:
    if TASK_STOP_REQUEST.is_symlink() or getattr(TASK_STOP_REQUEST, "is_junction", lambda: False)():
        return False
    try:
        raw = TASK_STOP_REQUEST.read_bytes()
        TASK_STOP_REQUEST.unlink(missing_ok=True)
        data = json.loads(raw.decode("utf-8"))
        stamp = _TaskDateTime.fromisoformat(data["requested_at"])
        return (data.get("task_id") == task_id and
                abs((_TaskDateTime.now(_TaskTZ.utc) - stamp).total_seconds()) <= 120)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        return False


def _task_telegram_response(update: Any, paired_chat: str, *,
                            status_line: str, tasks_line: str, logs_line: str,
                            now: int | None = None) -> str | None:
    global _poller_telegram_original
    from local_agent import poller
    original = _poller_telegram_original or poller._telegram_command_response
    if not isinstance(update, dict):
        return original(update, paired_chat, status_line=status_line,
                        tasks_line=tasks_line, logs_line=logs_line, now=now)
    msg = update.get("message")
    raw = msg.get("text") if isinstance(msg, dict) else None
    if isinstance(raw, str) and raw.strip().split("@", 1)[0].lower() == "/stop-task":
        # Delegate all chat, sender, date and length checks to the existing gate.
        checked = json.loads(json.dumps(update))
        checked["message"]["text"] = "/status"
        authorized = original(checked, paired_chat, status_line=status_line,
                              tasks_line=tasks_line, logs_line=logs_line, now=now)
        if authorized is None:
            return None
        if not _task_request_stop():
            return "Сейчас нет активной задачи для остановки."
        return "Остановка текущей задачи запрошена. Входные данные останутся в журнале; повтор запускается командой resume_task с ID задачи."
    response = original(update, paired_chat, status_line=status_line,
                        tasks_line=tasks_line, logs_line=logs_line, now=now)
    if response and isinstance(raw, str) and raw.strip().split("@", 1)[0].lower() == "/help":
        return response + "\n/stop-task — остановить текущую задачу и сохранить её входные данные"
    return response


def _task_terminate_tree(proc: Any) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            _task_subprocess.run(["taskkill.exe", "/PID", str(proc.pid), "/T", "/F"],
                                 stdin=_task_subprocess.DEVNULL,
                                 stdout=_task_subprocess.DEVNULL,
                                 stderr=_task_subprocess.DEVNULL, timeout=15, check=False)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    else:
        try:
            os.killpg(proc.pid, _task_signal.SIGTERM)
            proc.wait(timeout=2)
        except Exception:
            try:
                os.killpg(proc.pid, _task_signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass



def _task_read_worker_result(journal: TaskJournal, attempt: int) -> dict | None:
    path = journal.directory / ("attempt-%03d-result.json" % attempt)
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or set(data) - {"status", "error_type"}
                or not isinstance(data.get("status"), str) or len(data["status"]) > 32):
            return None
        return data
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def _task_stop_worker(client: Any, task: Any, journal: TaskJournal,
                      attempt: int, proc: Any, reason: str,
                      *, superseded_by: str | None = None) -> dict:
    _task_terminate_tree(proc)
    completed = _task_read_worker_result(journal, attempt)
    if completed is not None:
        status = completed["status"]
        journal.finish_attempt(attempt, status, reason="result_published_before_stop",
                               result_status=status, error_type=completed.get("error_type"))
        return {"status": status, "result_was_published": True}
    journal.finish_attempt(attempt, "interrupted", reason=reason)
    result = {"task_id": task.task_id, "status": "interrupted", "reason": reason,
              "resume_available": True}
    if superseded_by:
        result["superseded_by"] = superseded_by
    _task_publish_result(client, task.task_id, result)
    return {"status": "interrupted", "reason": reason}

def _task_worker_command(payload_path: _TaskPath) -> list[str]:
    return [sys.executable, "-m", "local_agent.mailbox_policy", "--task-worker", str(payload_path)]


def _task_launch_worker(client: Any, task: Any, expected_sha: str,
                        *, replay: bool = False, source_task_id: str | None = None) -> dict:
    journal = TaskJournal(task.task_id)
    if not replay:
        journal.save_input(_task_envelope(task), source_task_id=source_task_id)
    else:
        # Replays keep the original operation and arguments but get a fresh
        # mailbox identity so prior results remain immutable.
        old = TaskJournal(source_task_id or "").load_input()["envelope"]
        old.update({"task_id": task.task_id, "created_at": task.created_at,
                    "expires_at": task.expires_at})
        journal.save_input(old, source_task_id=source_task_id)
    state = journal.state()
    attempt = len(state.get("attempts", [])) + 1
    attempt_log = journal.directory / ("attempt-%03d.log" % attempt)
    if (attempt_log.is_symlink() or getattr(attempt_log, "is_junction", lambda: False)()
            or not attempt_log.resolve().is_relative_to(journal.directory.resolve())):
        raise TaskJournalError("Unsafe task attempt log")
    payload = {"envelope": journal.load_input()["envelope"],
               "expected_manifest_sha": expected_sha,
               "replay": replay, "source_task_id": source_task_id,
               "attempt": attempt}
    payload_path = journal.directory / ("attempt-%03d.json" % attempt)
    _task_atomic_json(payload_path, payload)
    with attempt_log.open("ab") as log_stream:
        kwargs: dict[str, Any] = {"cwd": str(_ROOT), "stdin": _task_subprocess.DEVNULL,
                                  "stdout": log_stream, "stderr": _task_subprocess.STDOUT}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(_task_subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        proc = _task_subprocess.Popen(_task_worker_command(payload_path), **kwargs)
    journal.add_attempt({"number": attempt, "started_at": _task_now(),
                         "status": "running", "pid": int(proc.pid),
                         "log": attempt_log.name,
                         "input_sha256": _task_hashlib.sha256(payload_path.read_bytes()).hexdigest()})
    _TASK_ACTIVE.clear()
    _TASK_ACTIVE.update({"proc": proc, "journal": journal, "task": task,
                         "attempt": attempt, "source_task_id": source_task_id,
                         "client": client})
    _task_publish_active(task.task_id, int(proc.pid))
    rejected_control_sha = None
    try:
        while True:
            return_code = proc.poll()
            if return_code is not None:
                current = journal.state()
                if current.get("status") == "running":
                    worker_result = _task_read_worker_result(journal, attempt)
                    if worker_result is not None:
                        journal.finish_attempt(attempt, worker_result["status"],
                                               exit_code=int(return_code),
                                               result_status=worker_result["status"],
                                               error_type=worker_result.get("error_type"))
                    else:
                        failure_reason = "worker_completed_without_result" if return_code == 0 else "worker_exit_without_result"
                        journal.finish_attempt(attempt, "failed", exit_code=int(return_code), reason=failure_reason)
                        _task_publish_result(client, task.task_id, {
                            "task_id": task.task_id, "status": "error",
                            "reason": failure_reason, "worker_exit_code": int(return_code),
                            "resume_available": True,
                        })
                return {"status": journal.state().get("status", "failed"), "exit_code": int(return_code)}
            _task_publish_active(task.task_id, int(proc.pid))
            if _task_consume_stop(task.task_id):
                return _task_stop_worker(client, task, journal, attempt, proc, "operator_stop")
            try:
                from local_agent.poller import _touch_mailbox_heartbeat
                _touch_mailbox_heartbeat()
            except Exception:
                pass
            try:
                latest = client.fetch_desired_task()
            except Exception:
                _task_time.sleep(5)
                continue
            if latest is not None:
                new_task, new_sha = latest
                if new_task.task_id != task.task_id or new_sha != expected_sha:
                    if new_task.operation in _CONTROL_OPERATIONS and not _task_control_authorized(new_task):
                        if rejected_control_sha != new_sha:
                            _task_publish_result(client, new_task.task_id, {
                                "task_id": new_task.task_id, "status": "blocked",
                                "reason": "local_approval_required_for_task_control"})
                            rejected_control_sha = new_sha
                        _task_time.sleep(5)
                        continue
                    stopped = _task_stop_worker(client, task, journal, attempt, proc,
                                                "superseded_by_new_desired_task",
                                                superseded_by=new_task.task_id)
                    if stopped.get("result_was_published"):
                        return stopped
                    if new_task.operation in _CONTROL_OPERATIONS:
                        return _task_handle_control(client, new_task, new_sha, locally_authorized=True)
                    return stopped
            _task_time.sleep(5)
    finally:
        _task_clear_active(task.task_id)
        _TASK_ACTIVE.clear()


def _task_handle_control(client: Any, task: Any, manifest_sha: str, *, locally_authorized: bool = False) -> dict:
    operation = task.operation
    args = task.arguments
    from local_agent import poller
    if not poller._not_expired(task):
        result = {"task_id": task.task_id, "status": "rejected", "reason": "expired_or_invalid_expiry"}
        _task_publish_result(client, task.task_id, result)
        return result
    if not locally_authorized and not _task_control_authorized(task):
        result = {"task_id": task.task_id, "status": "blocked",
                  "reason": "local_approval_required_for_task_control"}
        _task_publish_result(client, task.task_id, result)
        return result
    if operation == "stop_task":
        active = dict(_TASK_ACTIVE)
        result = {"task_id": task.task_id, "status": "completed",
                  "details": {"stopped_task_id": active.get("task").task_id if active.get("task") else None}}
        _task_publish_result(client, task.task_id, result)
        return result
    target = args["task_id"]
    journal = TaskJournal(target)
    if operation == "cancel_task":
        active = dict(_TASK_ACTIVE)
        if active and (active.get("task").task_id == target or active.get("source_task_id") == target):
            _task_terminate_tree(active["proc"])
            active["journal"].finish_attempt(active["attempt"], "cancelled", reason="operator_cancel")
            _task_publish_result(client, active["task"].task_id, {
                "task_id": active["task"].task_id, "status": "cancelled", "reason": "operator_cancel"})
        else:
            try:
                journal.load_input()
            except TaskJournalError:
                result = {"task_id": task.task_id, "status": "rejected", "reason": "task_input_not_found"}
                _task_publish_result(client, task.task_id, result)
                return result
            state = journal.state()
            if state.get("status") not in {"interrupted", "failed", "running", "queued"}:
                result = {"task_id": task.task_id, "status": "rejected", "reason": "task_not_cancellable"}
                _task_publish_result(client, task.task_id, result)
                return result
            journal.update("cancelled", reason="operator_cancel")
        result = {"task_id": task.task_id, "status": "completed",
                  "details": {"cancelled_task_id": target}}
        _task_publish_result(client, task.task_id, result)
        return result
    if operation == "resume_task":
        state = journal.state()
        if state.get("status") not in {"interrupted", "failed", "running"}:
            result = {"task_id": task.task_id, "status": "rejected", "reason": "task_not_resumable"}
            _task_publish_result(client, task.task_id, result)
            return result
        saved = journal.load_input()["envelope"]
        replay_env = dict(saved)
        replay_env.update({"task_id": task.task_id, "created_at": task.created_at,
                           "expires_at": task.expires_at})
        from local_agent import github_queue
        replay_task = github_queue.parse_task(json.dumps(replay_env, ensure_ascii=False))
        return _task_launch_worker(client, replay_task, manifest_sha, replay=True, source_task_id=target)
    return {"status": "rejected", "reason": "unknown_control"}


def _task_control_authorized(task: Any) -> bool:
    """Require local unattended opt-in or an interactive local YES."""
    try:
        policy = load_policy()
    except MailboxPolicyError:
        return False
    if policy["enabled"]:
        return True
    if not sys.stdin.isatty():
        return False
    try:
        return input("Approve this task control locally? Type YES to run: ").strip() == "YES"
    except (EOFError, OSError):
        return False


def _task_run_one(client: Any, task: Any, expected_manifest_sha: str | None = None) -> None:
    if task.operation in _CONTROL_OPERATIONS:
        _task_handle_control(client, task, expected_manifest_sha or "")
        return
    _task_launch_worker(client, task, expected_manifest_sha or "")


def _task_install_poller_hooks() -> Any:
    global _poller_run_one_original, _poller_telegram_original
    from local_agent import poller
    install_task_control_parser()
    if _poller_run_one_original is None:
        _poller_run_one_original = poller._run_one
        _poller_telegram_original = poller._telegram_command_response
        poller._telegram_command_response = _task_telegram_response
        poller._run_one = _task_run_one
    return poller


def _task_worker(payload_path: str) -> int:
    poller = _task_install_poller_hooks()
    path = _TaskPath(payload_path).resolve()
    if not path.is_relative_to(TASK_RUNS_DIR.resolve()) or path.is_symlink():
        return 2
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(payload, dict) or set(payload) != {
                "envelope", "expected_manifest_sha", "replay", "source_task_id", "attempt"}):
            return 2
        task = poller._github_queue.parse_task(json.dumps(payload["envelope"], ensure_ascii=False))
        client = poller.GitHubQueueClient(poller.QueueConfig.from_environment())
        expected_sha = payload["expected_manifest_sha"]
        if payload["replay"]:
            current = client.fetch_desired_task()
            if current is None or current[0].task_id != task.task_id or current[1] != expected_sha:
                return 3
            client.fetch_desired_task = lambda: (task, expected_sha)
        else:
            current = client.fetch_desired_task()
            if current is None or current[0] != task or current[1] != expected_sha:
                return 3
        original_publish = poller._publish_result_durable
        def tracked_publish(queue_client: Any, task_id: str, result: dict):
            published = original_publish(queue_client, task_id, result)
            if task_id == task.task_id:
                try:
                    journal = TaskJournal(task.task_id)
                    number = int(payload["attempt"])
                    status = str(result.get("status", "unknown"))[:32]
                    error_type = result.get("error_type")
                    item = {"status": status}
                    if isinstance(error_type, str):
                        item["error_type"] = error_type[:64]
                    _task_atomic_json(journal.directory / ("attempt-%03d-result.json" % number), item)
                except Exception:
                    pass
            return published
        poller._publish_result_durable = tracked_publish
        _poller_run_one_original(client, task, expected_manifest_sha=expected_sha)
        return 0
    except Exception as exc:
        print("Task worker failed:", type(exc).__name__)
        return 1



def _task_publish_result(client: Any, task_id: str, result: dict) -> Any:
    from local_agent import poller
    return poller._publish_result_durable(client, task_id, result)

def _task_supervisor() -> int:
    poller = _task_install_poller_hooks()
    original_popen = _task_subprocess.Popen
    python = str(sys.executable).casefold()
    def routed_popen(args, *pargs, **kwargs):
        try:
            seq = list(args) if not isinstance(args, str) else []
            if (len(seq) == 3 and str(seq[0]).casefold() == python
                    and seq[1:3] == ["-m", "local_agent.poller"]):
                seq = [seq[0], "-m", "local_agent.mailbox_policy", "--mailbox-worker"]
                args = seq
        except Exception:
            pass
        return original_popen(args, *pargs, **kwargs)
    _task_subprocess.Popen = routed_popen
    try:
        return poller.supervise_windows()
    finally:
        _task_subprocess.Popen = original_popen


def _task_mailbox_worker() -> int:
    poller = _task_install_poller_hooks()
    return poller.main()


def _task_cli(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--supervise"]:
        return _task_supervisor()
    if args == ["--mailbox-worker"]:
        return _task_mailbox_worker()
    if len(args) == 2 and args[0] == "--task-worker":
        return _task_worker(args[1])
    return 2


if __name__ == "__main__":
    raise SystemExit(_task_cli())
