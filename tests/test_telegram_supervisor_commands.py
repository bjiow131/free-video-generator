"""Telegram command authorization and supervisor restart contracts (offline)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from local_agent import poller, mailbox_policy


@pytest.fixture
def control(tmp_path, monkeypatch):
    monkeypatch.setattr(mailbox_policy, "_ROOT", tmp_path)
    monkeypatch.setattr(mailbox_policy, "POLICY_FILE", tmp_path / ".local_agent" / "mailbox_policy.json")
    monkeypatch.setattr(mailbox_policy, "RUNTIME_CONTROL_FILE",
                        tmp_path / ".local_agent" / "runtime_control.json")
    monkeypatch.setattr(mailbox_policy, "TELEGRAM_NOTIFICATIONS",
                        tmp_path / ".local_agent" / "telegram_notifications.json")
    return tmp_path


def update(command="/status", chat=112233, sender=112233, chat_type="private", when=10_000):
    return {"update_id": 33, "message": {
        "date": when, "text": command,
        "chat": {"id": chat, "type": chat_type},
        "from": {"id": sender}}}


def invoke(item, **kwargs):
    return poller._telegram_command_response(
        item, "112233", status_line="OK", tasks_line="Task report",
        logs_line="logs", now=10_000, **kwargs)


def test_private_pairing_requires_matching_sender_and_chat(control):
    assert invoke(update("/status")) == "OK"
    assert invoke(update("/status", chat=999)) is None
    assert invoke(update("/status", sender=999)) is None
    assert invoke(update("/status", chat_type="group")) is None
    assert invoke(update("/status", when=9_000)) is None
    assert invoke(update("/status", when=10_100)) is None
    assert invoke({"update_id": 22, "message": {"text": "/restart"}}) is None


def test_commands_are_fixed_not_arbitrary_shell(control):
    assert invoke(update("/tasks")) == "Task report"
    assert invoke(update("/logs")) == "logs"
    assert "/restart" in invoke(update("/help"))
    assert "Неизвестная" in invoke(update("/rm"))
    assert "только команды" in invoke(update("hello"))
    assert "только команды" in invoke(update("/restart NOW"))
    assert mailbox_policy.load_runtime_control()["restart_requested"] == 0


def test_restart_request_idempotent_and_ack(control):
    assert "запрошен" in invoke(update("/restart"))
    assert mailbox_policy.load_runtime_control()["restart_requested"] == 1
    assert "запрошен" in invoke(update("/restart"))
    assert mailbox_policy.load_runtime_control()["restart_requested"] == 1
    assert mailbox_policy.acknowledge_runtime_restart()
    assert not mailbox_policy.acknowledge_runtime_restart()
    invoke(update("/restart"))
    assert mailbox_policy.load_runtime_control()["restart_requested"] == 2


def test_pause_resume_persist(control):
    assert "приостановлен" in invoke(update("/pause"))
    assert mailbox_policy.load_runtime_control()["paused"] is True
    assert "возобновлён" in invoke(update("/resume"))
    assert mailbox_policy.load_runtime_control()["paused"] is False


def test_bad_control_file_fails_closed(control):
    destination = mailbox_policy.RUNTIME_CONTROL_FILE
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text('{"paused":"yes"}', encoding="utf-8")
    with pytest.raises(mailbox_policy.MailboxPolicyError):
        mailbox_policy.request_runtime_restart({})
    with pytest.raises(mailbox_policy.MailboxPolicyError):
        mailbox_policy.set_runtime_pause({"paused": True})


def test_cursor_file_prevents_replay(control, tmp_path, monkeypatch):
    monkeypatch.setattr(poller, "ROOT", tmp_path)
    monkeypatch.setattr(poller, "_TELEGRAM_UPDATES_STATE",
                        tmp_path / ".local_agent" / "telegram_updates_state.json")
    assert poller._read_telegram_offset() == 0
    poller._save_telegram_offset(203)
    assert poller._read_telegram_offset() == 203
    assert json.loads(poller._TELEGRAM_UPDATES_STATE.read_text()) == {"next_offset": 203}


def test_known_paired_chat_is_only_one_sent_command(control, monkeypatch, tmp_path):
    monkeypatch.setattr(poller, "ROOT", tmp_path)
    monkeypatch.setattr(poller, "_TELEGRAM_UPDATES_STATE",
                        tmp_path / ".local_agent" / "telegram_updates_state.json")
    from local_agent import studio_server as studio
    monkeypatch.setattr(studio, "_telegram_credentials", lambda: ("fake-token", "112233"))
    sent = []
    def api(_token, method, data, **kw):
        if method == "getUpdates":
            assert data["offset"] == len(sent) and not data["timeout"]
            return {"ok": True, "result": [
                {**update("/status", when=int(__import__("time").time())), "update_id": 0},
                {**update("/status", chat=777, when=int(__import__("time").time())), "update_id": 1},
            ] if not sent else []}
        assert method == "sendMessage"
        sent.append(data)
        return {"ok": True}
    monkeypatch.setattr(studio, "_telegram_call", api)
    poller._supervisor_telegram_poll_once("OK", "task", "log")
    assert len(sent) == 1
    assert sent[0]["chat_id"] == "112233"
    assert poller._read_telegram_offset() == 2
