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


def test_publish_preserves_first_result_for_task_after_restart(tmp_path):
    outbox = ResultOutbox(tmp_path)
    outbox.enqueue("task-004", {"status": "completed", "details": {"video": "render.mp4"}})
    client = FakeClient()

    outbox.publish(client, "task-004", {"status": "interrupted"})

    assert client.published == [
        ("task-004", {"status": "completed", "details": {"video": "render.mp4"}})
    ]
    assert not (tmp_path / "task-004.json").exists()


def test_pending_task_ids_includes_malformed_entries_for_recovery(tmp_path):
    outbox = ResultOutbox(tmp_path)
    (tmp_path / "task-005.json").write_text("{broken", encoding="utf-8")

    assert outbox.pending_task_ids() == {"task-005"}


def test_oversized_task_result_publishes_explicit_summary_without_raw_payload(tmp_path, monkeypatch):
    from local_agent import poller

    outbox = ResultOutbox(tmp_path)
    monkeypatch.setattr(poller, "_result_outbox", lambda: outbox)
    client = FakeClient()
    raw = "private_reference_data_" * 5000
    payload = {
        "task_id": "huge-review",
        "status": "blocked",
        "local_report_path": r"C:\AI-Agent-Workspace\reports\huge.json",
        "details": {"raw_render": raw},
    }
    assert poller._publish_result_durable(client, "huge-review", payload) == "fake-commit-sha"
    assert len(client.published) == 1
    task_id, published = client.published[0]
    assert task_id == "huge-review"
    assert published["status"] == "blocked"
    assert published["mailbox_delivery"] == "summary_only"
    assert published["details_omitted"] is True
    assert published["reason"] == "result_exceeds_mailbox_limit"
    assert published["local_report_path"] == payload["local_report_path"]
    assert raw not in json.dumps(published)
    assert not list(tmp_path.glob("*.json"))


def test_oversized_task_summary_remains_durable_during_network_failure(tmp_path, monkeypatch):
    from local_agent import poller

    outbox = ResultOutbox(tmp_path)
    monkeypatch.setattr(poller, "_result_outbox", lambda: outbox)
    payload = {
        "status": "completed",
        "local_report_path": "report.json",
        "details": {"large": "X" * 70000},
    }
    with pytest.raises(QueueTransportError):
        poller._publish_result_durable(FakeClient(fail=True), "huge-offline", payload)

    pending = tmp_path / "huge-offline.json"
    assert pending.is_file()
    assert pending.stat().st_size < 64000
    online = FakeClient()
    assert outbox.flush(online) == {"published": 1, "deferred": 0, "invalid": 0}
    assert online.published[0][1]["mailbox_delivery"] == "summary_only"
    assert online.published[0][1]["status"] == "completed"
    assert not pending.exists()
