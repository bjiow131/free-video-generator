"""Strict, non-executable task protocol for the future local control channel.

Security boundary: remote messages are data, never shell commands. This module
validates task envelopes only; it intentionally does not execute tasks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
import re

PROTOCOL_VERSION = 1
ALLOWED_OPERATIONS = frozenset({"status", "doctor", "test", "logs", "start", "stop", "backup"})
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class ProtocolError(ValueError):
    """Raised when a task envelope is malformed or requests unsafe behavior."""


@dataclass(frozen=True)
class TaskEnvelope:
    protocol_version: int
    task_id: str
    operation: str
    created_at: str
    expires_at: str
    requires_local_approval: bool
    arguments: dict[str, Any]


def parse_task(raw: str, *, max_bytes: int = 16_384) -> TaskEnvelope:
    """Parse a bounded JSON task and reject unknown fields/operations."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > max_bytes:
        raise ProtocolError("Task payload is missing or exceeds the size limit.")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ProtocolError("Task payload must be valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ProtocolError("Task envelope must be a JSON object.")

    required = {
        "protocol_version", "task_id", "operation", "created_at",
        "expires_at", "requires_local_approval", "arguments",
    }
    if set(value) != required:
        raise ProtocolError("Task envelope fields do not match protocol version 1.")
    if value["protocol_version"] != PROTOCOL_VERSION:
        raise ProtocolError("Unsupported protocol version.")
    if not isinstance(value["task_id"], str) or not TASK_ID_RE.fullmatch(value["task_id"]):
        raise ProtocolError("Invalid task_id.")
    if value["operation"] not in ALLOWED_OPERATIONS:
        raise ProtocolError("Operation is not allowlisted.")
    if not isinstance(value["created_at"], str) or not isinstance(value["expires_at"], str):
        raise ProtocolError("Task timestamps must be strings.")
    if value["requires_local_approval"] is not True:
        raise ProtocolError("All remote tasks must require local approval in the initial protocol.")
    if not isinstance(value["arguments"], dict):
        raise ProtocolError("arguments must be a JSON object.")
    if len(json.dumps(value["arguments"], ensure_ascii=False).encode("utf-8")) > 8_192:
        raise ProtocolError("Task arguments exceed the size limit.")

    # The initial protocol allows no free-form command, script, URL, or executable path.
    forbidden_keys = {"command", "cmd", "shell", "script", "executable", "url", "powershell"}
    if any(str(key).lower() in forbidden_keys for key in value["arguments"]):
        raise ProtocolError("Free-form command and executable fields are prohibited.")

    return TaskEnvelope(
        protocol_version=value["protocol_version"],
        task_id=value["task_id"],
        operation=value["operation"],
        created_at=value["created_at"],
        expires_at=value["expires_at"],
        requires_local_approval=value["requires_local_approval"],
        arguments=value["arguments"],
    )
