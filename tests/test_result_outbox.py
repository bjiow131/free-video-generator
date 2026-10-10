"""Regression tests for durable local result delivery."""
import json

import pytest

from local_agent.github_queue import QueueTransportError
from local_agent.result_outbox import ResultOutbox, ResultOutboxError


class FakeClient:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.published = []

    def publish_result(self, task_id, result):
        if self.fail:
            raise QueueTransportError("network unavailable")
        self.published.append((task_id, result))
        return "fake-commit-sha"


def test_failed_publication_is_retained_and_retried_with_secrets_redacted(tmp_path):
    outbox = ResultOutbox(tmp_path)
    offline = FakeClient(fail=True)
    result = {"status": "completed", "github_token": "ghp_do_not_leak"}

    with pytest.raises(QueueTransportError):
        outbox.publish(offline, "task-001", result)

    pending = tmp_path / "task-001.json"
    assert pending.is_file()
    assert "ghp_do_not_leak" not in pending.read_text(encoding="utf-8")

    online = FakeClient()
    summary = outbox.flush(online)
    assert summary == {"published": 1, "deferred": 0, "invalid": 0}
    assert online.published == [("task-001", {"status": "completed", "github_token": "[REDACTED]"})]
    assert not pending.exists()


def test_outbox_refuses_to_replace_an_existing_task_result(tmp_path):
    outbox = ResultOutbox(tmp_path)
    outbox.enqueue("task-002", {"status": "failed"})
    with pytest.raises(ResultOutboxError, match="different result"):
        outbox.enqueue("task-002", {"status": "completed"})


def test_flush_keeps_malformed_entry_for_manual_diagnosis(tmp_path):
    outbox = ResultOutbox(tmp_path)
    malformed = tmp_path / "task-003.json"
    malformed.write_text("{broken", encoding="utf-8")

    summary = outbox.flush(FakeClient())
    assert summary == {"published": 0, "deferred": 0, "invalid": 1}
    assert malformed.exists()
