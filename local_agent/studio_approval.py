"""Local, one-task-at-a-time approval handoff between the poller and Studio UI."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any


_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_MAX_REQUEST_BYTES = 60_000


class StudioApprovalError(RuntimeError):
    """Raised when an approval request is invalid, stale, or unsafe to modify."""


class StudioApprovalStore:
    """File-backed approval queue shared by the mailbox poller and local Studio."""

    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir)
        self.request_path = self.state_dir / "studio_approval_request.json"
        self.decisions_dir = self.state_dir / "studio_approval_decisions"

    def _ensure_dirs(self) -> None:
        if self.state_dir.is_symlink() or getattr(self.state_dir, "is_junction", lambda: False)():
            raise StudioApprovalError("Approval state directory is unsafe")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if not self.state_dir.resolve().is_dir():
            raise StudioApprovalError("Approval state directory is unavailable")
        if self.decisions_dir.is_symlink() or getattr(self.decisions_dir, "is_junction", lambda: False)():
            raise StudioApprovalError("Approval decisions directory is unsafe")
        self.decisions_dir.mkdir(exist_ok=True)

    @staticmethod
    def _expiry(value: str) -> datetime:
        if not isinstance(value, str):
            raise StudioApprovalError("Task expiry is invalid")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise StudioApprovalError("Task expiry is invalid") from exc
        if parsed.tzinfo is None:
            raise StudioApprovalError("Task expiry must include a timezone")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _decision_path(task_id: str, directory: Path) -> Path:
        digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
        return directory / (digest + ".json")

    @staticmethod
    def _read(path: Path, limit: int = _MAX_REQUEST_BYTES) -> dict[str, Any] | None:
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise StudioApprovalError("Approval file is unsafe")
        if not path.exists():
            return None
        if not path.is_file() or path.stat().st_size > limit:
            raise StudioApprovalError("Approval file is invalid")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StudioApprovalError("Approval file cannot be read") from exc
        if not isinstance(value, dict):
            raise StudioApprovalError("Approval file must contain an object")
        return value

    @staticmethod
    def _atomic_write(path: Path, value: dict[str, Any]) -> None:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > _MAX_REQUEST_BYTES:
            raise StudioApprovalError("Approval request is too large")
        descriptor, temporary = tempfile.mkstemp(prefix="studio-approval-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def create_request(self, task: Any) -> dict[str, Any]:
        self._ensure_dirs()
        task_id = getattr(task, "task_id", None)
        operation = getattr(task, "operation", None)
        arguments = getattr(task, "arguments", None)
        created_at = getattr(task, "created_at", None)
        expires_at = getattr(task, "expires_at", None)
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise StudioApprovalError("Task ID is invalid")
        if not isinstance(operation, str) or len(operation) > 100:
            raise StudioApprovalError("Task operation is invalid")
        if not isinstance(arguments, dict):
            raise StudioApprovalError("Task arguments are invalid")
        expiry = self._expiry(expires_at)
        if expiry <= datetime.now(timezone.utc):
            raise StudioApprovalError("Task has expired")
        previous = self._read(self.request_path)
        if previous and previous.get("task_id") != task_id:
            if self._expiry(previous.get("expires_at", "")) > datetime.now(timezone.utc):
                raise StudioApprovalError("Another task is awaiting local approval")
        decision_path = self._decision_path(task_id, self.decisions_dir)
        if decision_path.exists() or decision_path.is_symlink():
            raise StudioApprovalError("Task already has an approval decision")
        request = {
            "schema_version": 1,
            "task_id": task_id,
            "operation": operation,
            "arguments": arguments,
            "created_at": created_at,
            "expires_at": expires_at,
        }
        self._atomic_write(self.request_path, request)
        return request

    def get_pending(self) -> dict[str, Any] | None:
        self._ensure_dirs()
        request = self._read(self.request_path)
        if request is None:
            return None
        if not isinstance(request.get("task_id"), str) or not _TASK_ID.fullmatch(request["task_id"]):
            raise StudioApprovalError("Pending task ID is invalid")
        if self._expiry(request.get("expires_at", "")) <= datetime.now(timezone.utc):
            return None
        return request

    def decide(self, task_id: str, decision: str) -> dict[str, Any]:
        self._ensure_dirs()
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise StudioApprovalError("Task ID is invalid")
        if decision not in {"approve", "reject"}:
            raise StudioApprovalError("Decision must be approve or reject")
        request = self.get_pending()
        if request is None or request["task_id"] != task_id:
            raise StudioApprovalError("No matching task is awaiting approval")
        target = self._decision_path(task_id, self.decisions_dir)
        payload = json.dumps({
            "schema_version": 1,
            "task_id": task_id,
            "decision": decision,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }, separators=(",", ":")).encode("utf-8")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        flags |= getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(target, flags, 0o600)
        except FileExistsError as exc:
            raise StudioApprovalError("Task already has a decision") from exc
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return {"task_id": task_id, "decision": decision}

    def wait_for_decision(self, task_id: str, expires_at: str, timeout_seconds: int = 600) -> str:
        self._ensure_dirs()
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise StudioApprovalError("Task ID is invalid")
        expiry = self._expiry(expires_at)
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or timeout_seconds < 1:
            raise StudioApprovalError("Approval timeout is invalid")
        deadline = min(expiry.timestamp(), time.time() + timeout_seconds)
        target = self._decision_path(task_id, self.decisions_dir)
        while time.time() < deadline:
            decision = self._read(target, 4096)
            if decision is not None:
                if decision.get("task_id") != task_id or decision.get("decision") not in {"approve", "reject"}:
                    raise StudioApprovalError("Approval decision is invalid")
                target.unlink(missing_ok=True)
                return decision["decision"]
            time.sleep(min(0.25, max(0.01, deadline - time.time())))
        return "timeout"

    def clear_request(self, task_id: str) -> None:
        self._ensure_dirs()
        request = self._read(self.request_path)
        if request and request.get("task_id") == task_id:
            self.request_path.unlink(missing_ok=True)

    def request_and_wait(self, task: Any, timeout_seconds: int = 600) -> str:
        request = self.create_request(task)
        try:
            return self.wait_for_decision(request["task_id"], request["expires_at"], timeout_seconds)
        finally:
            self.clear_request(request["task_id"])
