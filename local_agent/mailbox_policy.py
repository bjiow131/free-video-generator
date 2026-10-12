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
    'doctor', 'preflight', 'status', 'octava_connectivity', 'blender_preflight',
    'blender_inspect_mia_project', 'blender_knowledge_search',
    'scan_project_assets', 'compile_story_plan',
})
BLENDER_OPERATIONS = frozenset({
    'save_story_plan', 'blender_forest_preview',
    'blender_mia_blockout', 'blender_mia_skeleton', 'export_mia_scene_review',
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
