"""Unit tests for the local control protocol and report redaction.

These tests are authored but have not been executed in this environment.
"""
import json
from pathlib import Path

import pytest

from local_agent.control_protocol import ProtocolError, parse_task
from local_agent.reporting import redact_text, write_report


def valid_task(**overrides):
    payload = {
        "protocol_version": 1,
        "task_id": "task-001",
        "operation": "doctor",
        "created_at": "2026-10-09T00:00:00Z",
        "expires_at": "2026-10-09T00:05:00Z",
        "requires_local_approval": True,
        "arguments": {},
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_parse_accepts_allowlisted_typed_operation():
    task = parse_task(valid_task())
    assert task.task_id == "task-001"
    assert task.operation == "doctor"
    assert task.requires_local_approval is True


@pytest.mark.parametrize("operation", ["shell", "powershell", "execute", "python"])
def test_parse_rejects_unknown_operation(operation):
    with pytest.raises(ProtocolError):
        parse_task(valid_task(operation=operation))


@pytest.mark.parametrize("key", ["command", "cmd", "shell", "script", "executable", "url"])
def test_parse_rejects_free_form_execution_fields(key):
    with pytest.raises(ProtocolError):
        parse_task(valid_task(arguments={key: "do something"}))


def test_parse_requires_local_approval():
    with pytest.raises(ProtocolError):
        parse_task(valid_task(requires_local_approval=False))


def test_parse_rejects_oversized_payload():
    with pytest.raises(ProtocolError):
        parse_task(valid_task(arguments={"data": "x" * 20_000}))


def test_redact_text_hides_common_secrets_and_home_path(monkeypatch):
    monkeypatch.setattr("local_agent.reporting._HOME", "/home/example")
    text = "api_key=abc123 path=/home/example/project"
    result = redact_text(text)
    assert "abc123" not in result
    assert "/home/example" not in result
    assert "[REDACTED]" in result
    assert "[USER_HOME]" in result


def test_report_writer_creates_local_json(tmp_path: Path):
    target = write_report(tmp_path, kind="doctor", status="collected", details={"note": "safe"})
    data = json.loads(target.read_text(encoding="utf-8"))
    assert target.parent == tmp_path
    assert data["schema_version"] == 1
    assert data["kind"] == "doctor"
    assert data["details"]["note"] == "safe"


def test_apply_patch_accepts_bounded_relative_diff():
    patch = "diff --git a/example.txt b/example.txt\\n--- a/example.txt\\n+++ b/example.txt\\n@@ -1 +1 @@\\n-old\\n+new\\n"
    task = parse_task(valid_task(operation="apply_patch", arguments={"patch": patch}))
    assert task.operation == "apply_patch"


@pytest.mark.parametrize("path", ["/outside.txt", "../outside.txt", "C:/outside.txt", ".git/config"])
def test_apply_patch_rejects_unsafe_paths(path):
    patch = f"diff --git a/{path} b/{path}\\n--- a/{path}\\n+++ b/{path}\\n@@ -1 +1 @@\\n-old\\n+new\\n"
    with pytest.raises(ProtocolError):
        parse_task(valid_task(operation="apply_patch", arguments={"patch": patch}))


def test_apply_patch_requires_patch_only_argument():
    with pytest.raises(ProtocolError):
        parse_task(valid_task(operation="apply_patch", arguments={"patch": "diff --git a/a b/a\\n", "extra": True}))
