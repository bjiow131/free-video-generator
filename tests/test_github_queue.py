"""Tests for the GitHub mailbox transport; all HTTP is mocked."""
import base64
import hashlib
import json

import pytest

from local_agent.github_queue import (
    GitHubQueueClient, QueueConfig, QueueConfigurationError, QueueTransportError,
)


class FakeResponse:
    def __init__(self, status_code=200, data=None, headers=None):
        self.status_code = status_code
        self._data = data or {}
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}

    def request(self, method, url, **kwargs):
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        return self.responses.pop(0)


def cfg():
    return QueueConfig(repository="owner/private-mailbox", token="test-token")


def test_fetch_desired_task_parses_valid_task():
    raw = json.dumps({
        "protocol_version": 1,
        "task_id": "task-42",
        "operation": "doctor",
        "created_at": "2026-10-09T10:00:00Z",
        "expires_at": "2026-10-09T10:05:00Z",
        "requires_local_approval": True,
        "arguments": {},
    }).encode()
    session = FakeSession([
        FakeResponse(data={"private": True}),
        FakeResponse(data={
            "type": "file", "encoding": "base64",
            "content": base64.b64encode(raw).decode(), "sha": "file-sha",
        }),
    ])
    task, sha = GitHubQueueClient(cfg(), session=session).fetch_desired_task()
    assert task.task_id == "task-42"
    assert sha == "file-sha"


def test_fetch_rejects_non_file_manifest():
    client = GitHubQueueClient(cfg(), session=FakeSession([
        FakeResponse(data={"private": True}),
        FakeResponse(data={"type": "dir"}),
    ]))
    with pytest.raises(QueueTransportError):
        client.fetch_desired_task()


def test_publish_result_creates_result_file_and_redacts_secrets():
    session = FakeSession([
        FakeResponse(data={"private": True}),
        FakeResponse(status_code=404),
        FakeResponse(data={"commit": {"sha": "commit-123"}}),
    ])
    sha = GitHubQueueClient(cfg(), session=session).publish_result(
        "task-42", {"status": "ok", "note": "api_key=abc123"}
    )
    assert sha == "commit-123"


def test_publish_result_rejects_path_traversal():
    client = GitHubQueueClient(cfg(), session=FakeSession([]))
    with pytest.raises(QueueConfigurationError):
        client.publish_result("../other", {"status": "ok"})



def test_public_mailbox_repository_is_refused():
    client = GitHubQueueClient(cfg(), session=FakeSession([
        FakeResponse(data={"private": False}),
    ]))
    with pytest.raises(QueueTransportError, match="not confirmed private"):
        client.fetch_desired_task()


def test_fetch_rejects_manifest_with_malformed_base64():
    raw = json.dumps({
        "protocol_version": 1,
        "task_id": "task-malformed",
        "operation": "doctor",
        "created_at": "2026-10-09T10:00:00Z",
        "expires_at": "2026-10-09T10:05:00Z",
        "requires_local_approval": True,
        "arguments": {},
    }).encode()
    malformed = base64.b64encode(raw).decode() + "!!!!"
    client = GitHubQueueClient(cfg(), session=FakeSession([
        FakeResponse(data={"private": True}),
        FakeResponse(data={
            "type": "file", "encoding": "base64",
            "content": malformed, "sha": "file-sha",
        }),
    ]))
    with pytest.raises(QueueTransportError, match="Task manifest rejected"):
        client.fetch_desired_task()



def test_fetch_accepts_whitespace_wrapped_base64():
    raw = json.dumps({
        "protocol_version": 1,
        "task_id": "task-wrapped",
        "operation": "doctor",
        "created_at": "2026-10-09T10:00:00Z",
        "expires_at": "2026-10-09T10:05:00Z",
        "requires_local_approval": True,
        "arguments": {},
    }).encode()
    encoded = base64.b64encode(raw).decode()
    wrapped = encoded[:24] + "\n" + encoded[24:]
    client = GitHubQueueClient(cfg(), session=FakeSession([
        FakeResponse(data={"private": True}),
        FakeResponse(data={
            "type": "file", "encoding": "base64",
            "content": wrapped, "sha": "file-sha",
        }),
    ]))
    task, sha = client.fetch_desired_task()
    assert task.task_id == "task-wrapped"
    assert sha == "file-sha"


def test_free_text_github_tokens_are_redacted():
    from local_agent.reporting import _redact_value
    values = _redact_value({
        "traceback": "failed ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "message": "bad github_pat_abcdefghijklmnopqrstuvwxyz0123456789",
    })
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in values["traceback"]
    assert "github_pat_abcdefghijklmnopqrstuvwxyz0123456789" not in values["message"]
    assert "[REDACTED]" in values["traceback"]
    assert "[REDACTED]" in values["message"]


def test_publish_repair_artifact_creates_immutable_patch():
    patch = "diff --git a/local_agent/fix.py b/local_agent/fix.py\n"
    session = FakeSession([
        FakeResponse(data={"private": True}),
        FakeResponse(status_code=404),
        FakeResponse(data={
            "content": {"sha": "blob-sha"},
            "commit": {"sha": "commit-sha"},
        }),
    ])
    result = GitHubQueueClient(cfg(), session=session).publish_repair_artifact("repair-01", patch)
    assert result["path"] == "queue/repair_results/repair-01.patch"
    assert result["sha256"] == hashlib.sha256(patch.encode()).hexdigest()
    assert result["commit_sha"] == "commit-sha"
    assert result["already_present"] is False


def test_publish_repair_artifact_is_idempotent_for_same_content():
    patch = "diff --git a/local_agent/fix.py b/local_agent/fix.py\n"
    encoded = base64.b64encode(patch.encode()).decode()
    session = FakeSession([
        FakeResponse(data={"private": True}),
        FakeResponse(data={"type": "file", "encoding": "base64", "content": encoded, "sha": "existing-blob"}),
    ])
    result = GitHubQueueClient(cfg(), session=session).publish_repair_artifact("repair-02", patch)
    assert result["already_present"] is True
    assert result["content_sha"] == "existing-blob"


def test_publish_repair_artifact_refuses_different_content_for_existing_id():
    existing_patch = "diff --git a/local_agent/old.py b/local_agent/old.py\n"
    requested_patch = "diff --git a/local_agent/new.py b/local_agent/new.py\n"
    encoded = base64.b64encode(existing_patch.encode()).decode()
    session = FakeSession([
        FakeResponse(data={"private": True}),
        FakeResponse(data={"type": "file", "encoding": "base64", "content": encoded, "sha": "existing-blob"}),
    ])
    client = GitHubQueueClient(cfg(), session=session)
    with pytest.raises(QueueConfigurationError, match="different content"):
        client.publish_repair_artifact("repair-03", requested_patch)
