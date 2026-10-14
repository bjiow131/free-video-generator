"""Tests for best-effort Windows notifications."""
from __future__ import annotations

import base64
import subprocess

from local_agent import notifications


def test_notification_is_noop_outside_windows(monkeypatch):
    monkeypatch.setattr(notifications.os, "name", "posix")
    monkeypatch.setattr(notifications, "_powershell_executable", lambda: "powershell.exe")
    called = []
    monkeypatch.setattr(notifications.subprocess, "Popen", lambda *a, **k: called.append((a, k)))
    assert notifications.notify_user(title="Failure", message="Report ready") is False
    assert called == []


def test_windows_notification_encodes_user_text_and_launches_hidden(monkeypatch):
    monkeypatch.setattr(notifications.os, "name", "nt")
    monkeypatch.setattr(notifications, "_powershell_executable", lambda: "powershell.exe")
    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(notifications.subprocess, "Popen", fake_popen)
    title = "Agent failed: don't run this"
    message = "Task <104> needs review"
    assert notifications.notify_user(title=title, message=message) is True
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == "powershell.exe"
    assert "-EncodedCommand" in args
    script = base64.b64decode(args[args.index("-EncodedCommand") + 1]).decode("utf-16le")
    assert title not in script
    assert message not in script
    assert base64.b64encode(title.encode()).decode() in script
    assert base64.b64encode(message.encode()).decode() in script
    assert "-WindowStyle" in args and "Hidden" in args
    assert kwargs["stdin"] == subprocess.DEVNULL


def test_notification_failure_is_nonfatal(monkeypatch):
    monkeypatch.setattr(notifications.os, "name", "nt")
    monkeypatch.setattr(notifications, "_powershell_executable", lambda: "powershell.exe")

    def fail(*args, **kwargs):
        raise OSError("not available")

    monkeypatch.setattr(notifications.subprocess, "Popen", fail)
    assert notifications.notify_user(title="Agent failed", message="Open report") is False
