"""Fetch and validate a reviewed repair from the private GitHub mailbox.

A repair is data (a unified diff), never a remote command. Application is handled
by the poller in an isolated Git worktree after explicit local approval.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from local_agent.github_queue import MAX_MANIFEST_BYTES, QueueTransportError

MAX_REPAIR_PATCH_BYTES = 40_000
_REPAIR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,59}$")
_SHA1 = re.compile(r"^[a-f0-9]{40}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_ALLOWED_PREFIXES = ("local_agent/", "tests/", "docs/", "scripts/")
_ALLOWED_ROOT_FILES = {"README.md", "requirements-github-mailbox.txt"}


class RepairProtocolError(ValueError):
    """Repair manifest or patch violates the narrow repair protocol."""


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise RepairProtocolError("repair timestamps must be strings")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RepairProtocolError("repair timestamps must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise RepairProtocolError("repair timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_one_path(raw_path: str) -> None:
    path = raw_path.strip()
    if path in {"/dev/null", "dev/null"}:
        return
    if path.startswith(("a/", "b/")):
        path = path[2:]
    if (not path or path.startswith("/") or "\\\\" in path or ":" in path
            or ".." in path.split("/") or path == ".git" or path.startswith(".git/")):
        raise RepairProtocolError("patch contains an unsafe path")
    if not (path.startswith(_ALLOWED_PREFIXES) or path in _ALLOWED_ROOT_FILES):
        raise RepairProtocolError("patch path is outside the repair allowlist")


def _validate_patch_paths(patch: str) -> None:
    headers = [line for line in patch.splitlines() if line.startswith("diff --git ")]
    if not headers:
        raise RepairProtocolError("patch has no git diff headers")
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) != 4:
                raise RepairProtocolError("malformed git diff header")
            _validate_one_path(parts[2])
            _validate_one_path(parts[3])
        elif line.startswith(("--- ", "+++ ")):
            _validate_one_path(line[4:])
        elif line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            _validate_one_path(line.split(" ", 2)[2])


def parse_repair_manifest(raw: str, *, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise RepairProtocolError("repair manifest missing or too large")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise RepairProtocolError("repair manifest must be valid UTF-8 JSON") from exc
    required = {
        "schema_version", "repair_id", "created_at", "expires_at",
        "requires_local_approval", "base_commit_sha", "patch_path", "patch_sha256",
    }
    if not isinstance(data, dict) or set(data) != required:
        raise RepairProtocolError("repair manifest fields do not match schema version 1")
    if isinstance(data["schema_version"], bool) or data["schema_version"] != 1:
        raise RepairProtocolError("unsupported repair schema version")
    if not isinstance(data["repair_id"], str) or not _REPAIR_ID.fullmatch(data["repair_id"]):
        raise RepairProtocolError("invalid repair_id")
    created = _parse_time(data["created_at"])
    expires = _parse_time(data["expires_at"])
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise RepairProtocolError("local clock must be timezone-aware")
    if created > current.astimezone(timezone.utc).replace(microsecond=0) and (created-current).total_seconds() > 300:
        raise RepairProtocolError("repair creation time is too far in the future")
    if expires <= created or expires <= current.astimezone(timezone.utc):
        raise RepairProtocolError("repair is expired or has invalid expiry")
    if (expires-created).total_seconds() > 86_400:
        raise RepairProtocolError("repair lifetime may not exceed 24 hours")
    if data["requires_local_approval"] is not True:
        raise RepairProtocolError("local approval is mandatory")
    if not isinstance(data["base_commit_sha"], str) or not _SHA1.fullmatch(data["base_commit_sha"]):
        raise RepairProtocolError("base_commit_sha must be a full Git commit SHA")
    patch_path = data["patch_path"]
    expected_prefix = f"queue/repairs/{data['repair_id']}.patch"
    if patch_path != expected_prefix:
        raise RepairProtocolError("patch_path must match queue/repairs/<repair_id>.patch")
    if not isinstance(data["patch_sha256"], str) or not _SHA256.fullmatch(data["patch_sha256"]):
        raise RepairProtocolError("patch_sha256 must be a SHA-256 hex digest")
    return data


def fetch_repair(client: Any) -> tuple[dict[str, Any], str, str] | None:
    """Fetch the current repair manifest and its referenced patch from the private mailbox."""
    client._require_private_repo()
    path = quote("queue/desired_repair.json", safe="/")
    response = client._request("GET", f"contents/{path}", params={"ref": client.config.ref})
    try:
        item = response.json()
        if item.get("type") != "file" or item.get("encoding") != "base64":
            raise RepairProtocolError("repair manifest must be a regular base64 file")
        raw_bytes = base64.b64decode("".join(item["content"].split()), validate=True)
        if len(raw_bytes) > MAX_MANIFEST_BYTES:
            raise RepairProtocolError("repair manifest exceeds the size limit")
        manifest = parse_repair_manifest(raw_bytes.decode("utf-8"))
        manifest_sha = str(item["sha"])
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        if isinstance(exc, RepairProtocolError):
            raise
        raise RepairProtocolError(f"repair manifest rejected: {type(exc).__name__}") from exc

    patch_api_path = f"contents/{quote(manifest['patch_path'], safe='/')}"
    patch_response = client._request("GET", patch_api_path, params={"ref": client.config.ref})
    try:
        patch_item = patch_response.json()
        if patch_item.get("type") != "file" or patch_item.get("encoding") != "base64":
            raise RepairProtocolError("repair patch must be a regular base64 file")
        patch_bytes = base64.b64decode("".join(patch_item["content"].split()), validate=True)
        if len(patch_bytes) > MAX_REPAIR_PATCH_BYTES:
            raise RepairProtocolError("repair patch exceeds the size limit")
        patch = patch_bytes.decode("utf-8")
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        if isinstance(exc, RepairProtocolError):
            raise
        raise RepairProtocolError(f"repair patch rejected: {type(exc).__name__}") from exc
    if hashlib.sha256(patch_bytes).hexdigest() != manifest["patch_sha256"]:
        raise RepairProtocolError("repair patch SHA-256 does not match the manifest")
    _validate_patch_paths(patch)
    if not patch.startswith("diff --git "):
        raise RepairProtocolError("repair patch is not a unified Git diff")
    return manifest, manifest_sha, patch
