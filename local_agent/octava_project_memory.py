"""Durable, credential-independent OctavAPI project checkpoints.

Stores only bounded text and logical step identifiers in the local workspace.
Never stores API keys, complete scripts, images, executable commands or full logs.
The approved content of a project session may be sent back to its AI provider.
"""
from __future__ import annotations

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
_LOCK = threading.RLock()
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


class ProjectMemory:
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
        with _LOCK:
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
                snapshot = ProjectMemory(workspace, project_id).snapshot()
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
