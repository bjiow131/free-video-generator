"""Mailbox idle alerts fire once after ten minutes without NEW tasks."""
from __future__ import annotations

from local_agent import poller, studio_server


def test_idleness_notice_only_once_per_idle_period(monkeypatch):
    queued = []
    saved = []
    flushed = []
    monkeypatch.setattr(poller, "_save_state", lambda value: saved.append(dict(value)))
    monkeypatch.setattr(studio_server, "telegram_queue_event",
                        lambda key, message: queued.append((key, message)) or True)
    monkeypatch.setattr(studio_server, "telegram_flush_outbox",
                        lambda **kw: flushed.append(kw) or 1)

    state = poller._mailbox_idle_initialize({}, now=1000)
    assert state["mailbox_last_new_task_at"] == 1000
    assert poller._mailbox_idle_tick(state, github_reachable=True, now=1599) == state
    assert queued == []

    state = poller._mailbox_idle_tick(state, github_reachable=True, now=1600)
    assert state["mailbox_idle_notice_sent"]
    assert len(queued) == 1
    assert "10 минут" in queued[0][1]
    assert "Проверка GitHub работает" in queued[0][1]
    assert len(saved) == 1
    assert flushed == [{"max_messages": 2}]

    # Repeat polling of the SAME manifest must not produce another message.
    state = poller._mailbox_idle_tick(state, github_reachable=True, now=3600)
    assert len(queued) == 1

    # A new unique task starts the next idle period.
    state = poller._mailbox_idle_new_task(state, now=4000)
    assert not state["mailbox_idle_notice_sent"]
    state = poller._mailbox_idle_tick(state, github_reachable=True, now=4599)
    assert len(queued) == 1
    state = poller._mailbox_idle_tick(state, github_reachable=True, now=4600)
    assert len(queued) == 2
    assert queued[0][0] != queued[1][0]


def test_disabled_telegram_retries_alert_after_reenable(monkeypatch):
    saved = []
    attempts = []
    ready = {"value": False}
    monkeypatch.setattr(poller, "_save_state", lambda value: saved.append(dict(value)))
    monkeypatch.setattr(studio_server, "telegram_queue_event",
                        lambda *args: attempts.append(args) or ready["value"])
    monkeypatch.setattr(studio_server, "telegram_flush_outbox", lambda **kw: 0)
    state = poller._mailbox_idle_initialize({}, now=2000)
    state = poller._mailbox_idle_tick(state, github_reachable=False, now=2600)
    assert not state["mailbox_idle_notice_sent"]
    assert not saved
    ready["value"] = True
    state = poller._mailbox_idle_tick(state, github_reachable=False, now=2601)
    assert state["mailbox_idle_notice_sent"]
    assert "ошибкой подключения" in attempts[-1][1]
    assert len(saved) == 1


def test_restart_preserves_idle_clock_and_no_duplicate_notice():
    old = {"mailbox_last_new_task_at": 1000.0, "mailbox_idle_notice_sent": True,
           "last_task_id": "previous"}
    assert poller._mailbox_idle_initialize(old, now=1900) is old
    assert poller._mailbox_idle_tick(old, github_reachable=True, now=1900) is old


def test_future_invalid_clock_recovers():
    state = {"mailbox_last_new_task_at": 999999999, "mailbox_idle_notice_sent": True}
    restored = poller._mailbox_idle_initialize(state, now=4000)
    assert restored["mailbox_last_new_task_at"] == 4000
    assert not restored["mailbox_idle_notice_sent"]


def test_no_github_task_counted_twice():
    state = {"last_task_id": "task-1", "manifest_sha": "sha-1",
             "processed_tasks": {"task-1": {"manifest_sha": "sha-1"}}}
    idle = poller._mailbox_idle_new_task(state, now=1234)
    assert poller.classify_manifest(idle, "task-1", "sha-1") == "same"
    assert poller.classify_manifest(idle, "task-2", "sha-2") == "new"
    assert idle["mailbox_last_new_task_at"] == 1234
