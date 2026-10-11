"""Regression tests for the local Telegram notifications switch."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from local_agent import studio_server, telegram_preferences
from local_agent.telegram_preferences import TelegramPreferenceError


@pytest.fixture
def local_preferences(tmp_path, monkeypatch):
    monkeypatch.setattr(telegram_preferences, "ROOT", tmp_path)
    monkeypatch.setattr(
        telegram_preferences, "PREFERENCE_PATH",
        tmp_path / ".local_agent" / "telegram_notifications.json",
    )
    monkeypatch.setattr(studio_server, "_TELEGRAM_OUTBOX", tmp_path / ".local_agent" / "telegram_outbox")
    monkeypatch.setattr(studio_server, "_telegram_credentials", lambda: ("mock-token", "mock-chat"))
    return tmp_path


def test_preexisting_paired_chat_remains_enabled_by_default(local_preferences):
    assert telegram_preferences.load_notifications() == {"enabled": True}
    assert studio_server.telegram_status()["notifications_enabled"] is True


def test_local_off_on_persists_and_rejects_extra_fields(local_preferences):
    result = studio_server.telegram_set_notifications({"enabled": False})
    assert result == {"notifications_enabled": False}
    assert studio_server.telegram_status()["enabled"] is False
    assert telegram_preferences.load_notifications() == {"enabled": False}
    result = studio_server.telegram_set_notifications({"enabled": True})
    assert result == {"notifications_enabled": True}
    assert studio_server.telegram_status()["enabled"] is True
    with pytest.raises(studio_server.TelegramAlertError):
        studio_server.telegram_set_notifications({"enabled": "false"})
    with pytest.raises(studio_server.TelegramAlertError):
        studio_server.telegram_set_notifications({"enabled": True, "token": "secret"})


def test_disabled_notifications_never_queue_or_send_and_clear_pending(local_preferences):
    with patch.object(studio_server, "_telegram_call", return_value={"ok": True}) as send:
        assert studio_server.telegram_queue_event("task:before", "First notice")
        outbox = studio_server._TELEGRAM_OUTBOX
        assert len(list(outbox.glob("*.json"))) == 1
        studio_server.telegram_set_notifications({"enabled": False})
        assert list(outbox.glob("*.json")) == []
        assert not studio_server.telegram_queue_event("task:after", "Second notice")
        assert studio_server.telegram_flush_outbox() == 0
        with pytest.raises(studio_server.TelegramAlertError):
            studio_server.telegram_send_test({})
        send.assert_not_called()
        studio_server.telegram_set_notifications({"enabled": True})
        assert studio_server.telegram_queue_event("task:new", "New notice")
        assert studio_server.telegram_flush_outbox() == 1
        send.assert_called_once()


def test_corrupt_preferences_fail_closed(local_preferences):
    path = telegram_preferences.PREFERENCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"enabled": "true"}), encoding="utf-8")
    assert telegram_preferences.notifications_enabled() is False
    assert not studio_server.telegram_queue_event("event:1", "Test")
    with pytest.raises(studio_server.TelegramAlertError):
        studio_server.telegram_status()


def test_symlink_preferences_are_rejected(local_preferences, tmp_path):
    source = tmp_path / "other.json"
    source.write_text('{"enabled":true}', encoding="utf-8")
    target = telegram_preferences.PREFERENCE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable on this system")
    assert not telegram_preferences.notifications_enabled()
    with pytest.raises(TelegramPreferenceError):
        telegram_preferences.save_notifications({"enabled": True})
