"""Regression tests for repeating 10-minute GitHub mailbox idle reminders."""
from __future__ import annotations

from local_agent import poller, studio_server


def test_idleness_notice_repeats_every_ten_minutes(monkeypatch):
    queued, saved, flushed = [], [], []
    monkeypatch.setattr(poller, "_save_state", lambda value: saved.append(dict(value)))
    monkeypatch.setattr(studio_server, "telegram_queue_event",
                        lambda key, message: queued.append((key, message)) or True)
    monkeypatch.setattr(studio_server, "telegram_flush_outbox",
                        lambda **kw: flushed.append(kw) or 1)

    state = poller._mailbox_idle_initialize({}, now=1000)
    assert poller._mailbox_idle_tick(state, github_reachable=True, now=1599) == state
    assert queued == []
    state = poller._mailbox_idle_tick(state, github_reachable=True, now=1600)
    assert len(queued) == 1
    assert state["mailbox_idle_last_notice_at"] == 1600
    assert "10 минут" in queued[-1][1]
    assert "Проверка GitHub работает" in queued[-1][1]

    state = poller._mailbox_idle_tick(state, github_reachable=True, now=2199)
    assert len(queued) == 1
    state = poller._mailbox_idle_tick(state, github_reachable=True, now=2200)
    assert len(queued) == 2
    assert state["mailbox_idle_last_notice_at"] == 2200
    assert "20 минут" in queued[-1][1]
    # Same event key per idle period limits offline queue buildup.
    assert queued[0][0] == queued[1][0]

    state = poller._mailbox_idle_tick(state, github_reachable=True, now=2800)
    assert len(queued) == 3
    assert "30 минут" in queued[-1][1]
    state = poller._mailbox_idle_tick(state, github_reachable=True, now=3000)
    assert len(queued) == 3

    state = poller._mailbox_idle_new_task(state, now=4000)
    assert not state["mailbox_idle_notice_sent"]
    assert state["mailbox_idle_last_notice_at"] is None
    state = poller._mailbox_idle_tick(state, github_reachable=True, now=4599)
    assert len(queued) == 3
    state = poller._mailbox_idle_tick(state, github_reachable=True, now=4600)
    assert len(queued) == 4
    assert queued[3][0] != queued[0][0]
    assert len(saved) == 4
    assert flushed == [{"max_messages": 2}] * 4


def test_disabled_telegram_retries_after_reenable(monkeypatch):
    saved, attempts = [], []
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
    assert state["mailbox_idle_last_notice_at"] == 2601
    assert "ошибкой подключения" in attempts[-1][1]
    state = poller._mailbox_idle_tick(state, github_reachable=False, now=3201)
    assert len(saved) == 2
    assert state["mailbox_idle_last_notice_at"] == 3201


def test_restarted_worker_keeps_reminder_clock(monkeypatch):
    queued = []
    monkeypatch.setattr(poller, "_save_state", lambda _: None)
    monkeypatch.setattr(studio_server, "telegram_queue_event",
                        lambda key, message: queued.append(key) or True)
    monkeypatch.setattr(studio_server, "telegram_flush_outbox", lambda **kw: 1)
    state = {"mailbox_last_new_task_at": 1000.0, "mailbox_idle_notice_sent": True,
             "mailbox_idle_last_notice_at": 1600.0}
    assert poller._mailbox_idle_initialize(state, now=2100) is state
    assert poller._mailbox_idle_tick(state, github_reachable=True, now=2199) is state
    assert not queued
    state = poller._mailbox_idle_tick(state, github_reachable=True, now=2200)
    assert len(queued) == 1


def test_legacy_one_shot_state_waits_before_first_repeated_reminder(monkeypatch):
    queued = []
    monkeypatch.setattr(poller, "_save_state", lambda _: None)
    monkeypatch.setattr(studio_server, "telegram_queue_event",
                        lambda key, message: queued.append(key) or True)
    monkeypatch.setattr(studio_server, "telegram_flush_outbox", lambda **kw: 1)
    legacy = {"mailbox_last_new_task_at": 1000.0, "mailbox_idle_notice_sent": True}
    migrated = poller._mailbox_idle_initialize(legacy, now=1900)
    assert migrated["mailbox_idle_last_notice_at"] == 1900
    assert poller._mailbox_idle_tick(migrated, github_reachable=True, now=2499) is migrated
    assert not queued
    updated = poller._mailbox_idle_tick(migrated, github_reachable=True, now=2500)
    assert updated["mailbox_idle_last_notice_at"] == 2500
    assert queued


def test_invalid_clock_recovers():
    state = {"mailbox_last_new_task_at": 999999999, "mailbox_idle_notice_sent": True}
    restored = poller._mailbox_idle_initialize(state, now=4000)
    assert restored["mailbox_last_new_task_at"] == 4000
    assert restored["mailbox_idle_last_notice_at"] is None
    assert not restored["mailbox_idle_notice_sent"]


def test_offline_retries_do_not_create_distinct_pending_event_keys(monkeypatch):
    pending = set()
    monkeypatch.setattr(poller, "_save_state", lambda _: None)
    monkeypatch.setattr(studio_server, "telegram_queue_event",
                        lambda key, message: pending.add(key) or True)
    monkeypatch.setattr(studio_server, "telegram_flush_outbox", lambda **kw: 0)
    state = poller._mailbox_idle_initialize({}, now=1000)
    for clock in (1600, 2200, 2800, 3400, 4000):
        state = poller._mailbox_idle_tick(state, github_reachable=False, now=clock)
    assert len(pending) == 1
    assert state["mailbox_idle_last_notice_at"] == 4000


def test_old_manifest_is_not_a_new_task():
    state = {"last_task_id": "task-1", "manifest_sha": "sha-1",
             "processed_tasks": {"task-1": {"manifest_sha": "sha-1"}}}
    idle = poller._mailbox_idle_new_task(state, now=1234)
    assert poller.classify_manifest(idle, "task-1", "sha-1") == "same"
    assert poller.classify_manifest(idle, "task-2", "sha-2") == "new"
    assert idle["mailbox_last_new_task_at"] == 1234
