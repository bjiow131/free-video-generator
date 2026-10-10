"""Durable local outbox for GitHub task results.

A result is written atomically before network publication. Failed publications
remain on disk and can be retried after connectivity returns.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from local_agent.github_queue import MAX_RESULT_BYTES, QueueTransportError
from local_agent.reporting import _redact_value

_SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ResultOutboxError(RuntimeError):
    """The local result outbox contains an invalid or conflicting entry."""


class ResultOutbox:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        if not isinstance(task_id, str) or not _SAFE_TASK_ID.fullmatch(task_id):
            raise ResultOutboxError("Invalid task ID for result outbox.")
        return self.root / (task_id + ".json")

    def enqueue(self, task_id: str, result: dict[str, Any]) -> Path:
        if not isinstance(result, dict):
            raise ResultOutboxError("Task result must be a JSON object.")
        target = self._path(task_id)
        envelope = {"schema_version": 1, "task_id": task_id, "result": _redact_value(result)}
        encoded = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_RESULT_BYTES:
            raise ResultOutboxError("Result exceeds the local outbox size limit.")
        if target.is_symlink():
            raise ResultOutboxError("Refusing a symlink in the result outbox.")
        if target.exists():
            existing = self._read(target, expected_task_id=task_id)
            if existing != envelope:
                raise ResultOutboxError("A different result already exists for this immutable task ID.")
            return target

        descriptor, temporary_name = tempfile.mkstemp(prefix="result.", suffix=".tmp", dir=str(self.root))
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            # The poller singleton lock prevents concurrent writers in normal
            # operation; refusing a newly appeared target avoids overwriting evidence.
            if target.exists() or target.is_symlink():
                raise ResultOutboxError("Result outbox entry appeared during write.")
            os.replace(temporary, target)
            return target
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _read(self, path: Path, *, expected_task_id: str) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise ResultOutboxError("Outbox entry must be a regular file.")
        if path.stat().st_size > MAX_RESULT_BYTES:
            raise ResultOutboxError("Outbox entry exceeds the size limit.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ResultOutboxError("Outbox entry is unreadable or malformed.") from exc
        if (not isinstance(data, dict) or data.get("schema_version") != 1
                or data.get("task_id") != expected_task_id or not isinstance(data.get("result"), dict)):
            raise ResultOutboxError("Outbox entry has an invalid schema or task ID.")
        return data

    def publish(self, client: Any, task_id: str, result: dict[str, Any]) -> str:
        """Persist first; remove the entry only after GitHub confirms publication."""
        path = self.enqueue(task_id, result)
        commit_sha = client.publish_result(task_id, _redact_value(result))
        path.unlink()
        return commit_sha

    def flush(self, client: Any) -> dict[str, int]:
        """Retry queued results. Invalid entries and network failures remain on disk."""
        published = deferred = invalid = 0
        for path in sorted(self.root.glob("*.json")):
            task_id = path.stem
            try:
                self._path(task_id)
                envelope = self._read(path, expected_task_id=task_id)
            except (ResultOutboxError, OSError):
                invalid += 1
                continue
            try:
                client.publish_result(task_id, envelope["result"])
            except QueueTransportError:
                deferred += 1
                continue
            path.unlink()
            published += 1
        return {"published": published, "deferred": deferred, "invalid": invalid}
