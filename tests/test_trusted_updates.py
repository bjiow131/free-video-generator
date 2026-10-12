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


def test_episode_asset_sync_paths_are_allowlisted_without_allowing_updater_self_update():
    paths = [
        "local_agent/control_protocol.py",
        "local_agent/github_asset_sync.py",
        "docs/season1/asset_sync_manifest.json",
        "tests/test_github_asset_sync.py",
        "tests/test_github_asset_sync_resume.py",
        "tests/test_asset_sync_protocol.py",
        "local_agent/mailbox_policy.py",
        "local_agent/studio_static/app.js",
        "tests/test_mailbox_policy.py",
    ]
    valid = manifest(files=[{"path": path, "sha256": "b"*64} for path in paths])
    parsed = update.parse_manifest(json.dumps(valid).encode())
    assert {item["path"] for item in parsed["files"]} == set(paths)

    blocked = manifest(files=[{"path": "local_agent/trusted_updates.py", "sha256": "b"*64}])
    with pytest.raises(update.TrustedUpdateError):
        update.parse_manifest(json.dumps(blocked).encode())


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


def test_supervisor_rapid_recovery_and_bounded_backoff():
    from local_agent.poller import _supervisor_restart_delay
    assert _supervisor_restart_delay(0, 15) == 2
    assert _supervisor_restart_delay(1, 1) == 4
    assert _supervisor_restart_delay(7, 0) == 60


def test_unattended_blender_command_remains_headless(tmp_path):
    from local_agent.blender_bridge import BlenderBridge
    from unittest.mock import Mock
    blender = tmp_path / "blender.exe"
    blender.write_bytes(b"fake")
    workspace = tmp_path / "workspace"
    def reject_after_assert(command, **kwargs):
        assert "--background" in command
        assert "--disable-autoexec" in command
        assert "--offline-mode" in command
        raise RuntimeError("stop test before launching Blender")
    bridge = BlenderBridge(blender, workspace, popen=reject_after_assert)
    import pytest
    with pytest.raises(RuntimeError, match="stop test"):
        bridge.run_task("forest_preview", project_name="headless_test")



def test_blender_executable_preflight_and_narrow_dialog_match(tmp_path):
    from local_agent.blender_locator import (
        is_supported_windows_blender, _matches_unsupported_16bit_dialog,
    )

    fake = tmp_path / "blender.exe"
    fake.write_bytes(b"placeholder")
    assert is_supported_windows_blender(fake) is False

    pe = bytearray(0x80 + 6)
    pe[:2] = b"MZ"
    pe[0x3C:0x40] = (0x80).to_bytes(4, "little")
    pe[0x80:0x84] = bytes((80, 69, 0, 0))
    pe[0x84:0x86] = (0x8664).to_bytes(2, "little")
    fake.write_bytes(pe)
    assert is_supported_windows_blender(fake) is True

    title = "Неподдерживаемое 16-разрядное приложение"
    body = f"Не удалось запустить {fake}: несовместимо с 64-разрядной версией Windows."
    assert _matches_unsupported_16bit_dialog(title, body, fake) is True
    assert _matches_unsupported_16bit_dialog("Ошибка", body, fake) is False
    assert _matches_unsupported_16bit_dialog(title, body, tmp_path / "other.exe") is False


def test_existing_skeleton_output_blocks_before_blender_launch(monkeypatch, tmp_path):
    from local_agent import blender_rigging as rigging

    blender = tmp_path / "blender.exe"
    blender.write_text("placeholder", encoding="utf-8")
    workspace = tmp_path / "workspace"
    project = workspace / "mia"
    project.mkdir(parents=True)
    (project / "mia_blockout.blend").write_bytes(b"blockout")
    output = project / "mia_skeleton.blend"
    output.write_bytes(b"keep")
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(blender))
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(workspace))

    def fail_if_launched(*_args, **_kwargs):
        raise AssertionError("Blender must not launch when the output already exists")

    monkeypatch.setattr(rigging.subprocess, "run", fail_if_launched)
    result = rigging.create_mia_skeleton("mia")
    assert result == {"status": "blocked", "reason": "skeleton_outputs_exist_no_overwrite"}
    assert output.read_bytes() == b"keep"


def test_telegram_notifications_disabled_until_paired(monkeypatch, tmp_path):
    from local_agent import studio_server as studio
    monkeypatch.setattr(studio, "_TELEGRAM_OUTBOX", tmp_path / "telegram_pending")
    monkeypatch.setattr(studio, "_telegram_credentials", lambda: (None, None))
    assert studio.telegram_status()["enabled"] is False
    assert studio.telegram_queue_event("job:test1", "Test message") is False
    assert not (tmp_path / "telegram_pending").exists()


def test_telegram_queue_is_idempotent_and_can_retry(monkeypatch, tmp_path):
    from local_agent import studio_server as studio
    token = "123456:" + "A" * 35
    sent = []
    monkeypatch.setattr(studio, "_TELEGRAM_OUTBOX", tmp_path / "telegram_pending")
    monkeypatch.setattr(studio, "_telegram_credentials", lambda: (token, "123"))
    def mock_call(_token, method, data, **kwargs):
        assert _token == token
        assert method == "sendMessage"
        sent.append(data)
        return {"ok": True}
    monkeypatch.setattr(studio, "_telegram_call", mock_call)
    assert studio.telegram_queue_event("scene:abc", "Scene ready") is True
    assert studio.telegram_queue_event("scene:abc", "Scene ready") is True
    assert len(list((tmp_path / "telegram_pending").glob("*.json"))) == 1
    assert studio.telegram_flush_outbox() == 1
    assert sent == [{"chat_id": "123", "text": "Scene ready"}]
    assert studio.telegram_flush_outbox() == 0


def test_telegram_pair_only_recent_unique_private_start(monkeypatch):
    import time
    from local_agent import studio_server as studio
    from local_agent import windows_credentials as creds
    token = "123456:" + "A" * 35
    values = {"token": token, "chat": None}
    monkeypatch.setattr(studio, "_telegram_credentials",
                        lambda: (values["token"], values["chat"]))
    def fake_write(value, *, target):
        if target == studio._TELEGRAM_CHAT_TARGET:
            values["chat"] = value
    monkeypatch.setattr(creds, "write_credential", fake_write)
    sent = []
    def fake_api(_token, method, data, **kwargs):
        assert _token == token
        if method == "getUpdates":
            return {"ok": True, "result": [
                {"message": {"date": int(time.time()), "text": "/start",
                             "chat": {"id": 333, "type": "private"},
                             "from": {"id": 333}}},
                {"message": {"date": int(time.time()), "text": "/start",
                             "chat": {"id": -888, "type": "group"},
                             "from": {"id": 444}}},
            ]}
        if method == "sendMessage":
            sent.append(data)
            return {"ok": True}
        raise AssertionError("Unapproved Telegram API method")
    monkeypatch.setattr(studio, "_telegram_call", fake_api)
    assert studio.telegram_pair_chat({})["paired"] is True
    assert sent[0]["chat_id"] == "333"
    assert values["chat"] == "333"


def test_telegram_invalid_tokens_cannot_build_api_urls():
    from local_agent import studio_server as studio
    with pytest.raises(studio.TelegramAlertError):
        studio._telegram_call("not-a-token", "sendMessage",
                              {"chat_id": "1", "text": "test"})
    with pytest.raises(studio.TelegramAlertError):
        studio._telegram_call("123456:" + "A" * 35, "deleteWebhook", {})



def test_telegram_switch_blocks_send_and_deletes_old_queue(tmp_path, monkeypatch):
    """Trusted-update smoke test: old Telegram pairing works without migration."""
    from local_agent import studio_server as studio, mailbox_policy as policy
    monkeypatch.setattr(policy, "_ROOT", tmp_path)
    monkeypatch.setattr(policy, "POLICY_FILE", tmp_path / ".local_agent" / "mailbox_policy.json")
    monkeypatch.setattr(policy, "TELEGRAM_NOTIFICATIONS", tmp_path / ".local_agent" / "telegram_notifications.json")
    monkeypatch.setattr(studio, "_TELEGRAM_OUTBOX", tmp_path / ".local_agent" / "telegram_outbox")
    monkeypatch.setattr(studio, "_telegram_credentials", lambda: ("dummy-token", "dummy-chat"))
    sent = []
    monkeypatch.setattr(studio, "_telegram_call",
                        lambda _token, method, data, **kw: sent.append(data) or {"ok": True})
    assert policy.load_telegram_notifications()["enabled"] is True
    assert studio.telegram_queue_event("camera:before", "Notification pending")
    assert len(list(studio._TELEGRAM_OUTBOX.glob("*.json"))) == 1
    assert studio.telegram_set_notifications({"enabled": False})["notifications_enabled"] is False
    assert len(list(studio._TELEGRAM_OUTBOX.glob("*.json"))) == 0
    assert not studio.telegram_queue_event("camera:after", "Should not be queued")
    assert studio.telegram_flush_outbox() == 0
    assert not sent
    assert studio.telegram_set_notifications({"enabled": True})["notifications_enabled"] is True
    assert studio.telegram_queue_event("camera:new", "Allowed")
    assert studio.telegram_flush_outbox() == 1
    assert len(sent) == 1


def test_mailbox_ten_minute_idle_notice_with_restart(tmp_path, monkeypatch):
    """Trusted-update smoke test: idle is measured since new task, never since poll."""
    from local_agent import poller, studio_server as studio
    saved = []
    queued = []
    monkeypatch.setattr(poller, "_save_state", lambda value: saved.append(dict(value)))
    monkeypatch.setattr(studio, "telegram_queue_event",
                        lambda key, msg: queued.append((key, msg)) or True)
    monkeypatch.setattr(studio, "telegram_flush_outbox", lambda **kw: 1)
    state = poller._mailbox_idle_initialize({}, now=1000)
    assert poller._mailbox_idle_tick(state, github_reachable=True, now=1599) == state
    assert queued == []
    state = poller._mailbox_idle_tick(state, github_reachable=True, now=1600)
    assert state["mailbox_idle_notice_sent"] is True
    assert "10 минут" in queued[-1][1]
    # Repeat the reminder after each ten-minute idle interval.
    repeated = poller._mailbox_idle_tick(state, github_reachable=True, now=2600)
    assert repeated["mailbox_idle_last_notice_at"] == 2600
    assert len(queued) == 2
    assert poller._mailbox_idle_initialize(repeated, now=3000) is repeated
    state = poller._mailbox_idle_new_task(repeated, now=3001)
    assert not state["mailbox_idle_notice_sent"]
    state = poller._mailbox_idle_tick(state, github_reachable=True, now=3601)
    assert state["mailbox_idle_notice_sent"] is True
    assert len(queued) == 3



def test_trusted_update_diagnostics_parser_redacts_arbitrary_output():
    from local_agent.poller import _parse_trusted_update_diagnostics

    raw = """FAILED tests/test_trusted_updates.py::test_gate - AssertionError: private-story-text
E   RuntimeError: ghp_secret_token
=========================== short test summary info ===========================
1 failed, 17 passed, 1 skipped in 2.04s
"""
    result = _parse_trusted_update_diagnostics(raw, 1)
    assert result["status"] == "failed"
    assert result["failed_tests"] == ["tests/test_trusted_updates.py::test_gate"]
    assert result["error_types"] == ["RuntimeError"]
    assert result["summary"] == "1 failed, 17 passed, 1 skipped"
    assert "private-story-text" not in repr(result)
    assert "ghp_secret_token" not in repr(result)


def test_trusted_update_diagnostics_requires_existing_tests_permission():
    from local_agent.mailbox_policy import default_policy, is_auto_authorized

    policy = default_policy()
    policy.update(enabled=True, allow_tests=True)
    assert is_auto_authorized("trusted_update_diagnostics", policy)
    policy["allow_tests"] = False
    assert not is_auto_authorized("trusted_update_diagnostics", policy)
    policy["enabled"] = False
    policy["allow_tests"] = True
    assert not is_auto_authorized("trusted_update_diagnostics", policy)


def test_episode_scene_review_export_dispatch_is_blender_gated():
    from local_agent import poller
    from local_agent.mailbox_policy import default_policy, is_auto_authorized

    operation = "export_mia_scene_review"
    assert operation in poller._SPECIALIZED_OPERATIONS
    policy = default_policy()
    policy.update(enabled=True, allow_blender=True)
    assert is_auto_authorized(operation, policy)
    policy["allow_blender"] = False
    assert not is_auto_authorized(operation, policy)
