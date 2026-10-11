"""Offline tests for optional Dropbox visual-QA export."""
from __future__ import annotations
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from local_agent import dropbox_review as mod


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "SETTINGS", tmp_path / ".local_agent" / "dropbox_review.json")
    monkeypatch.delenv("LOCAL_AGENT_DROPBOX_ROOT", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    return tmp_path


def test_export_is_off_by_default(isolated):
    assert mod.read_settings() == {"enabled": False}
    assert mod.export_review(isolated, {"job_id":"1"*32}, "ffmpeg") == {"status":"disabled"}


def test_consent_is_local_and_strict(isolated):
    with pytest.raises(mod.ReviewDeliveryError):
        mod.save_settings({"enabled": "yes"})
    with pytest.raises(mod.ReviewDeliveryError):
        mod.save_settings({"enabled": True, "command":"delete"})
    assert mod.save_settings({"enabled": True})["enabled"] is True
    assert mod.read_settings()["enabled"] is True


def test_desktop_root_from_official_account_config(isolated, monkeypatch):
    local = isolated / "AppData"
    (local / "Dropbox").mkdir(parents=True)
    drive = isolated / "SyncFolder"
    drive.mkdir()
    (local / "Dropbox" / "info.json").write_text(
        json.dumps({"personal":{"path":str(drive)}}), encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(local))
    assert mod.discover_dropbox_root() == drive.resolve()


def test_missing_desktop_sync_is_reported_not_guessed(isolated):
    mod.save_settings({"enabled": True})
    assert mod.review_status()["desktop_folder_detected"] is False
    video = isolated / "scene.mp4"
    video.write_bytes(b"\x00" * 500)
    with pytest.raises(mod.ReviewDeliveryError, match="Dropbox Desktop"):
        mod.export_review(isolated, {"job_id":"2"*32}, "ffmpeg")


def test_delivers_video_sheet_and_json_after_consent(isolated, monkeypatch):
    sync = isolated / "SyncFolder"
    sync.mkdir()
    monkeypatch.setenv("LOCAL_AGENT_DROPBOX_ROOT", str(sync))
    mod.save_settings({"enabled": True})
    job = isolated / "job"
    job.mkdir()
    (job / "scene.mp4").write_bytes(b"mp4" * 500)
    (job / "manifest.json").write_text(
        json.dumps({"fps":12,"duration":8,"camera":"tracking"}))
    seen = []
    def fake_run(args, **_):
        seen.append(args)
        Path(args[-1]).write_bytes(b"\xff\xd8" + b"\x00" * 300)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    out = mod.export_review(job, {"job_id":"3"*32,"kind":"scene","total_frames":96}, "ffmpeg")
    assert out["status"] == "exported_to_local_dropbox"
    folder = sync / "AI-Agent-Reviews" / ("3"*32)
    assert (folder / "preview.mp4").read_bytes() == (job / "scene.mp4").read_bytes()
    assert len(seen) == 1
    assert (folder / "frames.jpg").is_file()
    assert json.loads((folder / "camera.json").read_text())["camera"] == "tracking"
    assert json.loads((folder / "complete.json").read_text())["status"] == "completed"
    with pytest.raises(mod.ReviewDeliveryError, match="already exists"):
        mod.export_review(job, {"job_id":"3"*32}, "ffmpeg")


def test_video_export_failure_leaves_no_partial_public_review(isolated, monkeypatch):
    sync = isolated / "SyncFolder"
    sync.mkdir()
    monkeypatch.setenv("LOCAL_AGENT_DROPBOX_ROOT", str(sync))
    mod.save_settings({"enabled": True})
    job = isolated / "job"
    job.mkdir()
    (job / "scene.mp4").write_bytes(b"x" * 600)
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(mod.ReviewDeliveryError):
        mod.export_review(job, {"job_id":"4"*32}, "ffmpeg")
    assert not (sync / "AI-Agent-Reviews" / ("4"*32)).exists()
