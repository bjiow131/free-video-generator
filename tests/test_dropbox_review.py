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
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
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



def test_exports_only_fixed_episode1_draft_files_after_local_consent(isolated, monkeypatch):
    sync = isolated / "SyncFolder"
    sync.mkdir()
    monkeypatch.setenv("LOCAL_AGENT_DROPBOX_ROOT", str(sync))
    mod.save_settings({"enabled": True})
    workspace = isolated / "workspace"
    project = workspace / "S01E01_SC01_DRAFT"
    project.mkdir(parents=True)
    blend = b"BLENDERmock-project-draft"
    preview = bytes.fromhex("89504e470d0a1a0a") + b"preview"
    (project / "mia_blockout.blend").write_bytes(blend)
    (project / "mia_blockout.png").write_bytes(preview)

    result = mod.export_mia_scene_review(workspace, "S01E01_SC01_DRAFT")
    assert result["status"] == "exported_to_local_dropbox"
    folder = sync / "AI-Agent-Reviews" / result["folder"].split("/")[-1]
    assert (folder / "scene.blend").read_bytes() == blend
    assert (folder / "preview.png").read_bytes() == preview
    assert result["sha256"]["scene.blend"]
    assert json.loads((folder / "scene_manifest.json").read_text())["manual_visual_review_required"] is True
    assert json.loads((folder / "complete.json").read_text())["status"] == "completed"


def test_exports_fixed_episode1_release_with_silent_mp4_and_hashes(isolated, monkeypatch):
    sync = isolated / "SyncFolder"
    sync.mkdir()
    monkeypatch.setenv("LOCAL_AGENT_DROPBOX_ROOT", str(sync))
    mod.save_settings({"enabled": True})
    workspace = isolated / "workspace"
    project = workspace / "S01E01_SC01_RELEASE"
    project.mkdir(parents=True)
    blend = b"BLENDERmock-animated-project"
    preview = bytes.fromhex("89504e470d0a1a0a") + b"preview"
    video = b"\\x00\\x00\\x00\\x18ftypisom" + b"silent-video"
    (project / "mia_blockout.blend").write_bytes(blend)
    (project / "preview.png").write_bytes(preview)
    (project / "scene.mp4").write_bytes(video)

    result = mod.export_mia_scene_review(workspace, "S01E01_SC01_RELEASE")
    folder = sync / "AI-Agent-Reviews" / result["folder"].split("/")[-1]
    assert result["status"] == "exported_to_local_dropbox"
    assert (folder / "scene.blend").read_bytes() == blend
    assert (folder / "preview.png").read_bytes() == preview
    assert (folder / "preview.mp4").read_bytes() == video
    manifest = json.loads((folder / "scene_manifest.json").read_text())
    assert manifest["scene_status"] == "procedural_animatic_candidate"
    assert {item["name"] for item in manifest["files"]} == {"scene.blend", "preview.png", "preview.mp4"}
    assert result["sha256"]["preview.mp4"]


def test_episode1_export_is_disabled_without_local_dropbox_consent(isolated, monkeypatch):
    workspace = isolated / "workspace"
    project = workspace / "S01E01_SC01_DRAFT"
    project.mkdir(parents=True)
    (project / "mia_blockout.blend").write_bytes(b"blend")
    (project / "mia_blockout.png").write_bytes(b"png")
    assert mod.export_mia_scene_review(workspace, "S01E01_SC01_DRAFT")["status"] == "disabled"


def test_episode1_export_rejects_arbitrary_project_and_preserves_existing_data(isolated):
    with pytest.raises(mod.ReviewDeliveryError, match="fixed Episode 1"):
        mod.export_mia_scene_review(isolated, "../private")
    assert not (isolated / "AI-Agent-Reviews").exists()



def test_episode1_export_accepts_gzip_compressed_blend_header(isolated, monkeypatch):
    import gzip

    sync = isolated / "SyncFolder"
    sync.mkdir()
    monkeypatch.setenv("LOCAL_AGENT_DROPBOX_ROOT", str(sync))
    mod.save_settings({"enabled": True})
    project = isolated / "workspace" / "S01E01_SC01_DRAFT"
    project.mkdir(parents=True)
    (project / "mia_blockout.blend").write_bytes(gzip.compress(b"BLENDER-v500mock"))
    (project / "mia_blockout.png").write_bytes(bytes.fromhex("89504e470d0a1a0a") + b"preview")

    result = mod.export_mia_scene_review(project.parent, "S01E01_SC01_DRAFT")
    assert result["status"] == "exported_to_local_dropbox"


def test_desktop_root_from_local_appdata_account_config(isolated, monkeypatch):
    local = isolated / "LocalAppData"
    (local / "Dropbox").mkdir(parents=True)
    drive = isolated / "SyncFolderLocal"
    drive.mkdir()
    (local / "Dropbox" / "info.json").write_text(
        json.dumps({"business":{"path":str(drive)}}), encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert mod.discover_dropbox_root() == drive.resolve()
