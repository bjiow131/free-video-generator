from __future__ import annotations

import base64
import json
from io import BytesIO
from types import SimpleNamespace

import pytest

from local_agent import studio_server as studio
from local_agent import telegram_relay_server as relay


TOKEN = "123456:" + "A" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 100
JPEG = b"\xff\xd8\xff" + b"x" * 100


def photo_params(photo: bytes = JPEG, filename: str = "front.jpg") -> dict:
    return {
        "chat_id": "12345",
        "caption": "Mia front view",
        "filename": filename,
        "photo_base64": base64.b64encode(photo).decode("ascii"),
    }


def test_relay_accepts_only_small_front_jpeg_and_builds_multipart(monkeypatch):
    seen = {}

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return b'{"ok":true,"result":{"message_id":1}}'

    def open_request(request, timeout):
        seen["url"] = request.full_url
        seen["content_type"] = request.headers["Content-type"]
        seen["body"] = request.data
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr(relay, "build_opener", lambda *_: SimpleNamespace(open=open_request))
    monkeypatch.setattr(relay, "_limit", lambda: True)
    status, result = relay.forward({"token": TOKEN, "method": "sendPhoto", "params": photo_params()})
    assert status == 200 and result["ok"] is True
    assert seen["url"] == "https://api.telegram.org/bot" + TOKEN + "/sendPhoto"
    assert seen["content_type"].startswith("multipart/form-data; boundary=")
    assert b"name=\"chat_id\"" in seen["body"]
    assert b"name=\"photo\"; filename=\"front.jpg\"" in seen["body"]
    assert JPEG in seen["body"]


@pytest.mark.parametrize("params", [
    photo_params(PNG, "front.jpg"),
    photo_params(JPEG, "other.jpg"),
    {**photo_params(), "unexpected": "x"},
    {**photo_params(), "photo_base64": "not base64!"},
])
def test_relay_rejects_invalid_photo_envelopes(params):
    status, result = relay.forward({"token": TOKEN, "method": "sendPhoto", "params": params})
    assert status == 400
    assert result["ok"] is False


def test_local_sender_routes_front_jpeg_through_opted_in_relay(monkeypatch, tmp_path):
    monkeypatch.setattr(studio, "_telegram_credentials", lambda: (TOKEN, "12345"))
    monkeypatch.setattr(studio, "telegram_notifications_enabled", lambda: True)
    monkeypatch.setattr(studio, "telegram_transport_settings", lambda: {"use_relay": True})
    monkeypatch.setattr(studio, "_TELEGRAM_OUTBOX", tmp_path / ".local_agent" / "telegram_outbox")
    calls = []

    def send(token, method, data, *, timeout=10):
        calls.append((token, method, data, timeout))
        return {"ok": True}

    monkeypatch.setattr(studio, "_telegram_call", send)
    result = studio.telegram_send_mia_front_thumbnail("review-1", base64.b64encode(JPEG).decode("ascii"))
    assert result["status"] == "delivered"
    assert result["sent"] == ["front"]
    assert calls[0][1] == "sendPhoto"
    assert calls[0][2]["filename"] == "front.jpg"
    assert studio.telegram_send_mia_front_thumbnail("review-1", base64.b64encode(JPEG).decode("ascii"))["status"] == "already_delivered"
