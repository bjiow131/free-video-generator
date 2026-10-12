"""Offline contracts for private Telegram previews and the fixed Render media bridge."""
from __future__ import annotations

import base64
import json
import urllib.request
from pathlib import Path

import pytest

from local_agent import poller, studio_server, telegram_media, telegram_relay_server


TOKEN = "12345:" + "a" * 30
CHAT = "112233"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64
MP4 = b"\0\0\0\x18ftyp" + b"x" * 64


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(tmp_path))
    target = tmp_path / "mia_story"
    target.mkdir()
    return target


def completed(project, number=1, stamp=1.0):
    job_id = f"{number:032x}"
    folder = project / "studio_jobs" / job_id
    frames = folder / "frames"
    frames.mkdir(parents=True)
    (frames / "frame_0002.png").write_bytes(PNG)
    (folder / "scene.mp4").write_bytes(MP4)
    info = {
        "job_id": job_id, "state": "completed", "kind": "scene",
        "scene_id": "scene_001", "created_at": stamp, "total_frames": 2,
    }
    (folder / "job.json").write_text(json.dumps(info), encoding="utf-8")
    return folder, info


def test_preview_uses_exact_last_rendered_frame_and_newest_completed_job(project):
    one, _ = completed(project, number=1, stamp=1)
    two, _ = completed(project, number=2, stamp=2)
    assert telegram_media.resolve_media("preview")[0] == two / "frames" / "frame_0002.png"
    assert telegram_media.resolve_media("video")[0] == two / "scene.mp4"
    assert telegram_media.resolve_media("preview")[1] == "sendPhoto"
    assert telegram_media.resolve_media("video")[1] == "sendVideo"


def test_rejects_unauthorized_paths_and_unfinished_media(project):
    folder, info = completed(project)
    with pytest.raises(telegram_media.TelegramMediaError):
        telegram_media.resolve_media("../../secret")
    info["state"] = "running"
    with pytest.raises(telegram_media.TelegramMediaError):
        telegram_media.media_for_job(project, folder.name, "video", info)
    try:
        (folder / "frames" / "frame_0002.png").unlink()
        (folder / "frames" / "frame_0002.png").symlink_to(project / "outside.png")
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    with pytest.raises(telegram_media.TelegramMediaError):
        telegram_media.resolve_media("preview")


def test_reference_requires_existing_mia_reference(project):
    folder = project / "studio_media"
    folder.mkdir()
    name = "a" * 32 + ".png"
    (folder / name).write_bytes(PNG)
    (project / "studio_state.json").write_text(json.dumps({
        "characters": [{"id": "mia", "reference": name}],
    }), encoding="utf-8")
    path, method, caption = telegram_media.resolve_media("reference")
    assert path == folder / name and method == "sendPhoto"
    assert "Мия" in caption


class FakeReply:
    status = 200

    def __init__(self):
        self.body = b'{"ok":true,"result":{"message_id":1}}'

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, amount):
        return self.body[:amount]


def test_direct_media_is_binary_multipart_without_file_path(tmp_path, monkeypatch):
    image = tmp_path / "frame.png"
    image.write_bytes(PNG)
    seen = []
    monkeypatch.setattr(studio_server, "telegram_transport_settings", lambda: {"use_relay": False})
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda request, timeout: (seen.append(request) or FakeReply()))
    result = studio_server.telegram_upload_local_media(TOKEN, CHAT, "sendPhoto", image, "Test")
    assert result["ok"] is True
    assert seen[0].full_url.endswith("/sendPhoto")
    assert seen[0].data.count(PNG) == 1
    assert b"Content-Disposition: form-data" in seen[0].data
    assert b"\r\n" in seen[0].data
    assert str(image).encode() not in seen[0].data


def test_relay_media_uses_only_bounded_raw_bytes_and_fixed_endpoint(tmp_path, monkeypatch):
    image = tmp_path / "frame.png"
    image.write_bytes(PNG)
    seen = []
    monkeypatch.setattr(studio_server, "telegram_transport_settings", lambda: {"use_relay": True})
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda request, timeout: (seen.append(request) or FakeReply()))
    studio_server.telegram_upload_local_media(TOKEN, CHAT, "sendPhoto", image, "Привет")
    assert seen[0].full_url.endswith("/api/telegram/media")
    assert seen[0].data == PNG
    assert seen[0].get_header("X-telegram-method") == "sendPhoto"
    assert base64.urlsafe_b64decode(seen[0].get_header("X-telegram-caption")).decode() == "Привет"


def test_upload_rejects_bad_image_signature_before_network(tmp_path, monkeypatch):
    bad = tmp_path / "frame.png"
    bad.write_bytes(b"NOT A REAL IMAGE" * 5)
    monkeypatch.setattr(studio_server, "telegram_transport_settings", lambda: {"use_relay": False})
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *_a, **_kw: pytest.fail("Unexpected network call"))
    with pytest.raises(studio_server.TelegramAlertError):
        studio_server.telegram_upload_local_media(TOKEN, CHAT, "sendPhoto", bad, "Test")


def test_relay_rejects_bad_tokens_chats_bytes_and_poll_updates():
    caption = base64.urlsafe_b64encode("Мия".encode()).decode()
    relay = telegram_relay_server
    assert relay.forward_media("bad", CHAT, "sendPhoto", caption, PNG)[0] == 400
    assert relay.forward_media(TOKEN, "-1", "sendPhoto", caption, PNG)[0] == 400
    assert relay.forward_media(TOKEN, CHAT, "sendPhoto", caption, b"invalid" * 20)[0] == 415
    assert relay.forward_media(TOKEN, CHAT, "sendVideo", caption, b"invalid" * 20)[0] == 415
    # The independently-running Telegram supervisor requires these params.
    monkey = {"offset": 1, "limit": 20, "timeout": 0, "allowed_updates": ["message"]}
    # Use a fake non-network request when checking the validator.
    from unittest.mock import patch
    with patch.object(relay, "_limit", return_value=True), patch.object(relay, "build_opener") as op:
        op.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"ok":true,"result":[]}'
        op.return_value.open.return_value.__enter__.return_value.status = 200
        assert relay.forward({"token": TOKEN, "method": "getUpdates", "params": monkey})[0] == 200


def test_media_commands_are_private_and_have_no_path_arguments():
    def msg(command, user=CHAT):
        return {"message": {"date": 1000, "text": command,
                "chat": {"id": int(CHAT), "type": "private"},
                "from": {"id": int(user)}}}
    def reply(command, user=CHAT):
        return poller._telegram_command_response(
            msg(command, user), CHAT, status_line="ok", tasks_line="ok",
            logs_line="ok", now=1000)
    assert reply("/preview") == "@telegram-media:preview"
    assert reply("/video") == "@telegram-media:video"
    assert reply("/reference") == "@telegram-media:reference"
    assert reply("/preview C:/private/file.png").startswith("Поддерживаются")
    assert reply("/preview", "999") is None
