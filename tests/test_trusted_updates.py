"""Offline tests for opt-in, manifest integrity, rollback and replay safety."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_agent import trusted_updates as update


@pytest.fixture
def location(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "ROOT", tmp_path)
    monkeypatch.setattr(update, "OPT_IN", tmp_path / ".local_agent" / "trusted_updates_enabled.json")
    monkeypatch.setattr(update, "STATE_DIR", tmp_path / ".local_agent" / "trusted_updates")
    monkeypatch.setattr(update, "RECOVERY", tmp_path / ".local_agent" / "trusted_update_recovery.json")
    return tmp_path


def manifest(files=None, **overrides):
    now = datetime.now(timezone.utc)
    data = {
        "schema_version": 1,
        "update_id": "trust-test-01",
        "created_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(minutes=10)).isoformat(),
        "source_repo": update.SOURCE_REPO,
        "commit_sha": "a" * 40,
        "files": files or [{"path": "run_github_mailbox_agent.bat", "sha256": "b" * 64}],
    }
    data.update(overrides)
    return data


def test_disabled_by_default_until_explicit_local_ui_consent(location):
    assert update.get_opt_in() == {"enabled": False}
    assert update.set_opt_in({"enabled": True}) == {"enabled": True}
    assert update.get_opt_in()["enabled"]
    assert update.set_opt_in({"enabled": False}) == {"enabled": False}


@pytest.mark.parametrize("value", [{}, {"enabled": 1}, {"enabled": "true"},
                                   {"enabled": True, "command": "cmd"}, None])
def test_reject_bad_opt_in_value(location, value):
    with pytest.raises(update.TrustedUpdateError):
        update.set_opt_in(value)


def test_manifest_restricts_file_paths_and_untrusted_sources():
    valid = manifest()
    assert update.parse_manifest(json.dumps(valid).encode())["update_id"] == "trust-test-01"
    for changed in [
        manifest(source_repo="attacker/repo"),
        manifest(commit_sha="main"),
        manifest(update_id="../unsafe"),
        manifest(files=[{"path": "../../Windows/System32/cmd.exe", "sha256": "b"*64}]),
        manifest(files=[{"path": "local_agent/windows_credentials.py", "sha256": "b"*64}]),
        manifest(files=[{"path": "run_github_mailbox_agent.bat", "sha256": "invalid"}]),
        manifest(files=[{"path": "run_github_mailbox_agent.bat", "sha256": "b"*64}]*2),
        manifest(expires_at=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()),
    ]:
        with pytest.raises(update.TrustedUpdateError):
            update.parse_manifest(json.dumps(changed).encode())


def test_update_stages_and_keeps_backup(location):
    target = location / "run_github_mailbox_agent.bat"
    target.write_bytes(b"old safe launcher")
    payload = b"@echo off\nset LOCAL_AGENT_WORKSPACE=C:\\AI-Agent-Workspace\n"
    params = manifest(files=[{"path": "run_github_mailbox_agent.bat",
                               "sha256": hashlib.sha256(payload).hexdigest()}])
    out = update.apply_update(params, fetch_file=lambda *args: payload, run_tests=False)
    assert out["status"] == "completed"
    assert out["restart_needed"] is True
    assert target.read_bytes() == payload
    assert (location / ".local_agent" / "trusted_updates" / "trust-test-01" /
            "backup" / "run_github_mailbox_agent.bat").read_bytes() == b"old safe launcher"
    assert not update.RECOVERY.exists()


def test_failed_postinstall_tests_restore_original_files(location, monkeypatch):
    target = location / "run_github_mailbox_agent.bat"
    target.write_bytes(b"old original")
    payload = b"@echo off\nexit /b 0\n"
    params = manifest(files=[{"path": "run_github_mailbox_agent.bat",
                               "sha256": hashlib.sha256(payload).hexdigest()}])
    monkeypatch.setattr(update.subprocess, "run",
                        lambda *_a, **_kw: SimpleNamespace(returncode=1))
    with pytest.raises(update.TrustedUpdateError, match="tests failed"):
        update.apply_update(params, fetch_file=lambda *args: payload)
    assert target.read_bytes() == b"old original"
    assert not update.RECOVERY.exists()


def test_recovery_after_interrupted_update(location):
    dest = location / "run_github_mailbox_agent.bat"
    dest.write_text("new-broken")
    backup = location / ".local_agent" / "trusted_updates" / "trust-test-01" / "backup"
    backup.mkdir(parents=True)
    (backup / dest.name).write_text("old-working")
    update._write_json(update.RECOVERY, {"update_id": "trust-test-01",
                                        "files": [{"path": dest.name, "existed": True}]})
    assert update.recover_interrupted() is True
    assert dest.read_text() == "old-working"
    assert update.recover_interrupted() is False


def test_update_disallowed_with_no_local_consent(location, monkeypatch):
    class NoRemote:
        def __getattr__(self, _n):
            raise AssertionError("Must not poll when disabled")
    assert update.process_pending(NoRemote()) is None


def test_update_id_cannot_be_replayed(location, monkeypatch):
    update.set_opt_in({"enabled": True})
    m = manifest()
    state = update.STATE_DIR / "trust-test-01.json"
    update._write_json(state, {"manifest_sha": "sha-one", "status": "completed"})
    monkeypatch.setattr(update, "_fetch_manifest", lambda c: (m, "sha-one"))
    assert update.process_pending(object()) is None
    monkeypatch.setattr(update, "_fetch_manifest", lambda c: (m, "different-sha"))
    with pytest.raises(update.TrustedUpdateError, match="reused"):
        update.process_pending(object())


def test_refuses_symlinked_permission(location):
    external = location.parent / (location.name + "-external")
    external.write_text('{"enabled":true}')
    try:
        update.OPT_IN.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("Windows account cannot create symlinks")
    with pytest.raises(update.TrustedUpdateError):
        update.get_opt_in()


def test_studio_review_is_local_opt_in_and_does_not_assume_cloud_sync(tmp_path, monkeypatch):
    from local_agent import studio_server as studio
    monkeypatch.setattr(studio, "SETTINGS", tmp_path / "review.json")
    root = tmp_path / "Dropbox"
    root.mkdir()
    monkeypatch.setenv("LOCAL_AGENT_DROPBOX_ROOT", str(root))
    assert studio.read_settings() == {"enabled": False}
    assert studio.review_status()["desktop_folder_detected"] is True
    assert studio.review_status()["sync_verified"] is False
    with pytest.raises(studio.ReviewDeliveryError):
        studio.save_settings({"enabled": "yes"})
    studio.save_settings({"enabled": True})
    assert studio.read_settings()["enabled"] is True


def test_studio_visual_review_exports_only_after_local_permission(tmp_path, monkeypatch):
    from local_agent import studio_server as studio
    from types import SimpleNamespace

    monkeypatch.setattr(studio, "SETTINGS", tmp_path / "review.json")
    dropbox = tmp_path / "Dropbox"
    dropbox.mkdir()
    monkeypatch.setenv("LOCAL_AGENT_DROPBOX_ROOT", str(dropbox))
    job = tmp_path / "job"
    job.mkdir()
    (job / "scene.mp4").write_bytes(b"x" * 1024)
    info = {"job_id": "e" * 32, "state": "completed", "total_frames": 120}
    assert studio.export_review(job, info, "ffmpeg") == {"status": "disabled"}

    studio.save_settings({"enabled": True})
    def ffmpeg_fake(args, **_):
        Path(args[-1]).write_bytes(b"\xff\xd8" + b"p" * 600)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(studio.subprocess, "run", ffmpeg_fake)
    result = studio.export_review(job, info, "ffmpeg")
    assert result["status"] == "exported_to_local_dropbox"
    directory = dropbox / "AI-Agent-Reviews" / ("e" * 32)
    assert (directory / "preview.mp4").read_bytes() == b"x" * 1024
    assert (directory / "frames.jpg").is_file()
    assert json.loads((directory / "camera.json").read_text())["job_id"] == ("e" * 32)
    assert json.loads((directory / "complete.json").read_text())["status"] == "completed"
    with pytest.raises(studio.ReviewDeliveryError, match="already exists"):
        studio.export_review(job, info, "ffmpeg")


def test_offline_studio_import_without_third_party_packages(location):
    """Studio runs from its own venv, unlike GitHub polling and remote updates."""
    import subprocess
    import sys
    from local_agent import studio_server
    project_root = Path(studio_server.__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-S", "-c",
                             "import local_agent.studio_server; "
                             "print('offline-studio-import-ok')"],
                            cwd=project_root, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert "offline-studio-import-ok" in result.stdout


def test_studio_opt_in_file_compatible_with_unattended_updater(location, monkeypatch):
    """Two Python venvs share only local validated consent, not import dependencies."""
    from local_agent import mailbox_policy
    monkeypatch.setattr(mailbox_policy, "_ROOT", location)
    monkeypatch.setattr(mailbox_policy, "POLICY_FILE",
                        location / ".local_agent" / "mailbox_policy.json")
    monkeypatch.setattr(mailbox_policy, "_TRUSTED_UPDATES_OPT_IN", update.OPT_IN)
    assert mailbox_policy.get_trusted_update_opt_in() == {"enabled": False}
    mailbox_policy.set_trusted_update_opt_in({"enabled": True})
    assert update.get_opt_in() == {"enabled": True}
    mailbox_policy.set_trusted_update_opt_in({"enabled": False})
    assert update.get_opt_in() == {"enabled": False}
    with pytest.raises(mailbox_policy.MailboxPolicyError):
        mailbox_policy.set_trusted_update_opt_in({"enabled": 1})


def test_legacy_blender_scene_world_is_repaired_in_private_temporary_copy(tmp_path):
    from local_agent.studio_jobs import _prepare_studio_blender_script
    original = tmp_path / "old_scene.py"
    original.write_text(
        "def main():\n"
        "    bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "    scene.world.color = (0.08, 0.11, 0.16)\n",
        encoding="utf-8",
    )
    job = tmp_path / "render_job"
    job.mkdir()
    output = _prepare_studio_blender_script(original, job)
    assert output != original
    assert original.read_text(encoding="utf-8").count("worlds.new") == 0
    corrected = output.read_text(encoding="utf-8")
    assert 'if scene.world is None:' in corrected
    assert 'bpy.data.worlds.new' in corrected
    compile(corrected, str(output), "exec")


def test_fixed_blender_scene_uses_original_script(tmp_path):
    from local_agent.studio_jobs import _prepare_studio_blender_script
    fixed = tmp_path / "scene.py"
    fixed.write_text("def main():\n    pass\n", encoding="utf-8")
    assert _prepare_studio_blender_script(fixed, tmp_path) == fixed
