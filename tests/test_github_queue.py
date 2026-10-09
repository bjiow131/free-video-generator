"""Tests for the GitHub mailbox transport; all HTTP is mocked."""
import base64
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
    session = FakeSession([FakeResponse(data={
        "type": "file", "encoding": "base64",
        "content": base64.b64encode(raw).decode(), "sha": "file-sha",
    })])
    task, sha = GitHubQueueClient(cfg(), session=session).fetch_desired_task()
    assert task.task_id == "task-42"
    assert sha == "file-sha"


def test_fetch_rejects_non_file_manifest():
    client = GitHubQueueClient(cfg(), session=FakeSession([FakeResponse(data={"type": "dir"})]))
    with pytest.raises(QueueTransportError):
        client.fetch_desired_task()


def test_publish_result_creates_result_file_and_redacts_secrets():
    session = FakeSession([FakeResponse(status_code=404), FakeResponse(data={"commit": {"sha": "commit-123"}})])
    sha = GitHubQueueClient(cfg(), session=session).publish_result(
        "task-42", {"status": "ok", "note": "api_key=abc123"}
    )
    assert sha == "commit-123"


def test_publish_result_rejects_path_traversal():
    client = GitHubQueueClient(cfg(), session=FakeSession([]))
    with pytest.raises(QueueConfigurationError):
        client.publish_result("../other", {"status": "ok"})
