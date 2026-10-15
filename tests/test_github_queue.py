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


def test_fetch_treats_missing_backup_manifest_as_an_empty_queue():
    client = GitHubQueueClient(
        QueueConfig(repository="owner/backup-mailbox", token="test-token", missing_manifest_ok=True),
        session=FakeSession([
            FakeResponse(data={"private": True}),
            FakeResponse(status_code=404),
        ]),
    )
    assert client.fetch_desired_task() is None


def test_primary_missing_manifest_still_reports_configuration_error():
    client = GitHubQueueClient(cfg(), session=FakeSession([
        FakeResponse(data={"private": True}),
        FakeResponse(status_code=404),
    ]))
    with pytest.raises(QueueTransportError, match="not found"):
        client.fetch_desired_task()


def test_from_environment_all_adds_distinct_backup_using_same_credential(monkeypatch):
    monkeypatch.setenv("LOCAL_AGENT_GITHUB_REPO", "owner/primary-mailbox")
    monkeypatch.setenv("LOCAL_AGENT_GITHUB_BACKUP_REPO", "owner/backup-mailbox")
    monkeypatch.setenv("LOCAL_AGENT_ALLOW_ENV_TOKEN", "1")
    monkeypatch.setenv("LOCAL_AGENT_GITHUB_TOKEN", "test-token")
    configs = QueueConfig.from_environment_all()
    assert [item.repository for item in configs] == [
        "owner/primary-mailbox", "owner/backup-mailbox"
    ]
    assert configs[0].token == configs[1].token == "test-token"
    assert configs[1].missing_manifest_ok is True


def test_from_environment_all_rejects_same_primary_and_backup(monkeypatch):
    monkeypatch.setenv("LOCAL_AGENT_GITHUB_REPO", "owner/primary-mailbox")
    monkeypatch.setenv("LOCAL_AGENT_GITHUB_BACKUP_REPO", "OWNER/PRIMARY-MAILBOX")
    monkeypatch.setenv("LOCAL_AGENT_ALLOW_ENV_TOKEN", "1")
    monkeypatch.setenv("LOCAL_AGENT_GITHUB_TOKEN", "test-token")
    with pytest.raises(QueueConfigurationError, match="must be different"):
        QueueConfig.from_environment_all()

