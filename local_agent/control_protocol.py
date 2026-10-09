"""Strict, non-executable task protocol for the future local control channel.

Security boundary: remote messages are data, never shell commands. This module
validates task envelopes only; it intentionally does not execute tasks.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import json
import re

PROTOCOL_VERSION = 1
ALLOWED_OPERATIONS = frozenset({"status", "doctor", "preflight", "test", "logs", "start", "stop", "backup", "apply_patch", "blender_forest_preview", "save_story_plan", "compile_story_plan", "scan_project_assets", "blender_knowledge_search",\n    "blender_preflight", "blender_mia_blockout", "blender_preflight", "blender_mia_blockout"})
# These typed operations may be remotely authorized only when the local owner
# explicitly enables remote approval in the Windows environment. Code changes
# and generic test execution remain local-approval-only.
REMOTE_APPROVABLE_OPERATIONS = frozenset({
    "status", "doctor", "preflight", "logs", "blender_forest_preview",
    "save_story_plan", "compile_story_plan", "scan_project_assets", "blender_knowledge_search",
})
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
BLENDER_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")


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


def parse_task(raw: str, *, max_bytes: int = 65_536) -> TaskEnvelope:
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
    if isinstance(value["protocol_version"], bool) or not isinstance(value["protocol_version"], int) or value["protocol_version"] != PROTOCOL_VERSION:
        raise ProtocolError("Unsupported protocol version.")
    if not isinstance(value["task_id"], str) or not TASK_ID_RE.fullmatch(value["task_id"]):
        raise ProtocolError("Invalid task_id.")
    if not isinstance(value["operation"], str) or value["operation"] not in ALLOWED_OPERATIONS:
        raise ProtocolError("Operation is not allowlisted.")
    if not isinstance(value["created_at"], str) or not isinstance(value["expires_at"], str):
        raise ProtocolError("Task timestamps must be strings.")
    try:
        created_at = datetime.fromisoformat(value["created_at"].replace("Z", "+00:00"))
        expires_at = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolError("Task timestamps must use ISO 8601 format.") from exc
    if created_at.tzinfo is None or expires_at.tzinfo is None:
        raise ProtocolError("Task timestamps must include a timezone.")
    if expires_at <= created_at:
        raise ProtocolError("Task expiry must be later than task creation.")
    if (expires_at - created_at).total_seconds() > 86_400:
        raise ProtocolError("Task lifetime may not exceed 24 hours.")
    if not isinstance(value["requires_local_approval"], bool):
        raise ProtocolError("requires_local_approval must be a boolean.")
    if value["requires_local_approval"] is False and value["operation"] not in REMOTE_APPROVABLE_OPERATIONS:
        raise ProtocolError("This operation cannot use remote approval; local approval is mandatory.")
    if not isinstance(value["arguments"], dict):
        raise ProtocolError("arguments must be a JSON object.")
    if value["operation"] in {"status", "doctor", "preflight", "test", "logs", "start", "stop", "backup"} and value["arguments"]:
        raise ProtocolError("This operation does not accept arguments.")
    if len(json.dumps(value["arguments"], ensure_ascii=False).encode("utf-8")) > 49_152:
        raise ProtocolError("Task arguments exceed the size limit.")

    if value["operation"] == "preflight" and value["arguments"]:
        raise ProtocolError("preflight does not accept arguments.")
    if value["operation"] == "apply_patch":
        patch = value["arguments"].get("patch")
        if set(value["arguments"]) != {"patch"} or not isinstance(patch, str):
            raise ProtocolError("apply_patch requires exactly one string field named patch.")
        if len(patch.encode("utf-8")) > 40_000 or not patch.startswith("diff --git "):
            raise ProtocolError("Patch is missing a git diff header or exceeds the size limit.")
        for line in patch.splitlines():
            if line.startswith("diff --git "):
                parts = line.split()
                if len(parts) != 4:
                    raise ProtocolError("Malformed git diff header.")
                for path in parts[2:]:
                    normalized = path[2:] if path.startswith(("a/", "b/")) else path
                    # Git diff paths must use forward slashes; rejecting backslashes
                    # avoids Windows traversal variants such as "..\\outside.py".
                    if "\\" in normalized or normalized.startswith("/") or ":" in normalized or ".." in normalized.split("/"):
                        raise ProtocolError("Patch contains an unsafe path.")
                    if normalized == ".git" or normalized.startswith(".git/"):
                        raise ProtocolError("Patch may not modify Git metadata.")

    if value["operation"] == "blender_forest_preview":
        args = value["arguments"]
        allowed_args = {"project_name", "render", "preview", "cycles"}
        if set(args) - allowed_args or "project_name" not in args:
            raise ProtocolError("blender_forest_preview accepts project_name and optional render/preview/cycles booleans only.")
        if not isinstance(args["project_name"], str) or not BLENDER_PROJECT_RE.fullmatch(args["project_name"]):
            raise ProtocolError("Blender project_name must use 1-49 letters, digits, underscores, or hyphens.")
        for flag in ("render", "preview", "cycles"):
            if flag in args and not isinstance(args[flag], bool):
                raise ProtocolError(f"Blender argument {flag} must be a boolean.")

    if value["operation"] == "blender_preflight":
        if value["arguments"]:
            raise ProtocolError("blender_preflight does not accept arguments.")
    if value["operation"] == "blender_mia_blockout":
        args = value["arguments"]
        if set(args) - {"project_name"} or not isinstance(args.get("project_name"), str) or not BLENDER_PROJECT_RE.fullmatch(args["project_name"]):
            raise ProtocolError("blender_mia_blockout requires only a safe project_name.")
    if value["operation"] == "blender_knowledge_search":
        args = value["arguments"]
        if set(args) - {"query", "limit"} or not isinstance(args.get("query"), str):
            raise ProtocolError("blender_knowledge_search requires a query string and optional limit.")
        if not args["query"].strip() or len(args["query"]) > 1000:
            raise ProtocolError("Blender knowledge query must contain 1-1000 characters.")
        limit = args.get("limit", 5)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
            raise ProtocolError("Blender knowledge limit must be an integer from 1 to 10.")
    if value["operation"] == "scan_project_assets":
        args = value["arguments"]
        if set(args) != {"project_name"} or not isinstance(args.get("project_name"), str) or not BLENDER_PROJECT_RE.fullmatch(args["project_name"]):
            raise ProtocolError("scan_project_assets requires only a safe project_name.")
    if value["operation"] == "compile_story_plan":
        args = value["arguments"]
        if set(args) != {"project_name"} or not isinstance(args.get("project_name"), str) or not BLENDER_PROJECT_RE.fullmatch(args["project_name"]):
            raise ProtocolError("compile_story_plan requires only a safe project_name.")
    if value["operation"] == "save_story_plan":
        args = value["arguments"]
        if set(args) != {"story_plan"} or not isinstance(args["story_plan"], dict):
            raise ProtocolError("save_story_plan requires exactly one object field named story_plan.")
        if len(json.dumps(args["story_plan"], ensure_ascii=False).encode("utf-8")) > 48_000:
            raise ProtocolError("Story plan exceeds the 48 KB limit.")
        plan = args["story_plan"]
        if isinstance(plan.get("schema_version"), bool) or not isinstance(plan.get("schema_version"), int) or plan.get("schema_version") != 1:
            raise ProtocolError("Unsupported story plan schema_version.")
        project_name = plan.get("project_name")
        if not isinstance(project_name, str) or not BLENDER_PROJECT_RE.fullmatch(project_name):
            raise ProtocolError("Story plan project_name must use 1-48 letters, digits, underscores, or hyphens.")
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
