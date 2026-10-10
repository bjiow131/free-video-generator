"""Unit tests for the GitHub repair manifest protocol."""
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from local_agent.repair_channel import RepairProtocolError, parse_repair_manifest, _validate_patch_paths


def manifest(patch: str, **overrides):
    now = datetime.now(timezone.utc)
    value = {
        "schema_version": 1,
        "repair_id": "repair-test-01",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=20)).isoformat(),
        "requires_local_approval": True,
        "base_commit_sha": "a" * 40,
        "patch_path": "queue/repairs/repair-test-01.patch",
        "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
    }
    value.update(overrides)
    return json.dumps(value)


def test_parse_accepts_valid_repair_manifest():
    patch = "diff --git a/local_agent/example.py b/local_agent/example.py\n"
    parsed = parse_repair_manifest(manifest(patch))
    assert parsed["repair_id"] == "repair-test-01"
    assert parsed["requires_local_approval"] is True


@pytest.mark.parametrize("override", [
    {"requires_local_approval": False},
    {"base_commit_sha": "not-a-commit"},
    {"patch_path": "../outside.patch"},
    {"patch_sha256": "short"},
    {"repair_id": "../bad"},
])
def test_parse_rejects_unsafe_or_malformed_manifest(override):
    patch = "diff --git a/local_agent/example.py b/local_agent/example.py\n"
    with pytest.raises(RepairProtocolError):
        parse_repair_manifest(manifest(patch, **override))


def test_parse_rejects_expired_repair():
    patch = "diff --git a/local_agent/example.py b/local_agent/example.py\n"
    now = datetime.now(timezone.utc)
    raw = manifest(
        patch,
        created_at=(now - timedelta(hours=2)).isoformat(),
        expires_at=(now - timedelta(minutes=1)).isoformat(),
    )
    with pytest.raises(RepairProtocolError, match="expired"):
        parse_repair_manifest(raw)


@pytest.mark.parametrize("path", [
    "../outside.py",
    "local_agent/../../outside.py",
    ".git/config",
    "C:/Windows/file.py",
    "unknown_area/file.py",
])
def test_patch_paths_reject_traversal_and_unapproved_roots(path):
    patch = f"diff --git a/{path} b/{path}\n"
    with pytest.raises(RepairProtocolError):
        _validate_patch_paths(patch)


def test_patch_paths_accept_local_agent_and_tests():
    _validate_patch_paths(
        "diff --git a/local_agent/example.py b/local_agent/example.py\n"
        "diff --git a/tests/test_example.py b/tests/test_example.py\n"
    )

def test_patch_rejects_unapproved_path_in_unified_headers():
    patch = (
        "diff --git a/local_agent/example.py b/local_agent/example.py\n"
        "--- a/local_agent/example.py\n"
        "+++ b/unknown_area/payload.py\n"
    )
    with pytest.raises(RepairProtocolError, match="allowlist"):
        _validate_patch_paths(patch)

@pytest.mark.parametrize("header", [
    "diff --git local_agent/example.py b/local_agent/example.py",
    "diff --git a/local_agent/example.py local_agent/example.py",
])
def test_patch_rejects_noncanonical_diff_path_prefixes(header):
    with pytest.raises(RepairProtocolError, match="malformed git diff header"):
        _validate_patch_paths(header + "\\n")
