"""Tests for poller expiry and task supersession helpers."""
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path

import pytest

from local_agent.poller import _not_expired



def test_windows_error_mode_flags_are_applied_safely(monkeypatch):
    from local_agent import poller
    observed = []
    assert poller._apply_windows_error_mode(observed.append) is True
    assert observed == [0x0001 | 0x0002 | 0x8000]


def test_unsupported_16bit_dialog_requires_exact_title_class_and_message():
    from local_agent import poller
    russian = (
        "Не удалось запустить программу или компонент из-за несовместимости "
        "с 64-разрядной версией Windows."
    )
    assert poller._is_unsupported_16bit_dialog(
        "Неподдерживаемое 16-разрядное приложение", "#32770", russian)
    assert not poller._is_unsupported_16bit_dialog(
        "Неподдерживаемое 16-разрядное приложение", "Chrome_WidgetWin_1", russian)
    assert not poller._is_unsupported_16bit_dialog(
        "Ошибка приложения", "#32770", russian)
    assert not poller._is_unsupported_16bit_dialog(
        "Неподдерживаемое 16-разрядное приложение", "#32770", "Unrelated text")




def test_windows_error_mode_flags_are_applied_safely(monkeypatch):
    from local_agent import poller
    observed = []
    assert poller._apply_windows_error_mode(observed.append) is True
    assert observed == [0x0001 | 0x0002 | 0x8000]


def test_unsupported_16bit_dialog_requires_exact_title_class_and_message():
    from local_agent import poller
    russian = (
        "Не удалось запустить программу или компонент из-за несовместимости "
        "с 64-разрядной версией Windows."
    )
    assert poller._is_unsupported_16bit_dialog(
        "Неподдерживаемое 16-разрядное приложение", "#32770", russian)
    assert not poller._is_unsupported_16bit_dialog(
        "Неподдерживаемое 16-разрядное приложение", "Chrome_WidgetWin_1", russian)
    assert not poller._is_unsupported_16bit_dialog(
        "Ошибка приложения", "#32770", russian)
    assert not poller._is_unsupported_16bit_dialog(
        "Неподдерживаемое 16-разрядное приложение", "#32770", "Unrelated text")




def test_scheduled_task_target_diagnostic_only_returns_match(tmp_path):
    from local_agent import poller
    prefix = tmp_path / "AI-Agent"
    root = Path(str(prefix) + "-Studio-Octava")
    xml = (
        "<Task><Actions><Exec><Command>python.exe</Command>"
        "<Arguments>-c import os; os.chdir('"
        + str(root)
        + "')</Arguments></Exec></Actions></Task>"
    )
    assert poller._scheduled_task_targets_root(xml, root) is True
    assert poller._scheduled_task_targets_root(xml, prefix) is False
    assert poller._scheduled_task_targets_root(xml, tmp_path / "Other") is False
    assert poller._scheduled_task_targets_root("<Task>", root) is None
    assert poller._scheduled_task_targets_root("x" * 65537, root) is None
    assert str(root) not in str(poller._scheduled_task_targets_root(xml, root))




def test_mailbox_failure_diagnostics_exports_only_crash_metadata(monkeypatch, tmp_path):
    from local_agent import poller
    monkeypatch.setattr(poller, "ROOT", tmp_path)
    state = tmp_path / ".local_agent"
    state.mkdir()
    (state / "octava_supervisor.log").write_text(
        "mailbox exited code=1; auto-restarting\n"
        "Trusted update installed; controlled restart\n", encoding="utf-8")
    (state / "octava_mailbox.log").write_text(
        'Traceback (most recent call last):\n'
        '  File "C:\\private\\local_agent\\poller.py", line 123, in main\n'
        '    secret = "DO_NOT_EXPORT"\n'
        'RuntimeError: DO_NOT_EXPORT\n', encoding="utf-8")
    result = poller._mailbox_failure_diagnostics()
    assert result["last_mailbox_exit_code"] == 1
    assert result["last_exception_type"] == "RuntimeError"
    assert result["last_poller_frame"] == {"line": 123, "function": "main"}
    assert result["controlled_update_restart_count_in_log_tail"] == 1
    assert "DO_NOT_EXPORT" not in str(result)
    assert "private" not in str(result)


def test_mailbox_failure_diagnostics_handles_absent_logs(monkeypatch, tmp_path):
    from local_agent import poller
    monkeypatch.setattr(poller, "ROOT", tmp_path)
    result = poller._mailbox_failure_diagnostics()
    assert result["last_exception_type"] is None
    assert result["last_mailbox_exit_code"] is None


def test_mailbox_failure_diagnostics_rejects_log_symlink(monkeypatch, tmp_path):
    from local_agent import poller
    monkeypatch.setattr(poller, "ROOT", tmp_path)
    (tmp_path / ".local_agent").mkdir()
    outside = tmp_path / "other.log"
    outside.write_text("RuntimeError: private\n", encoding="utf-8")
    try:
        (tmp_path / ".local_agent" / "octava_mailbox.log").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    assert poller._mailbox_failure_diagnostics()["last_exception_type"] is None


def test_supervisor_recovery_invokes_batch_launcher_from_install_root(tmp_path, monkeypatch):
    from local_agent import poller
    root = tmp_path / "Studio folder's name"
    root.mkdir()
    launcher = root / "run_github_mailbox_agent.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr(poller.subprocess, "list2cmdline", lambda args: args)
    args = poller._supervisor_recovery_command(__import__("pathlib").Path(sys.executable), root)
    assert args == ["cmd.exe", "/d", "/c", str(launcher)]


def test_mailbox_process_diagnostics_never_exports_commands(monkeypatch):
    from local_agent import poller
    monkeypatch.setattr(poller.os, "name", "nt")
    monkeypatch.setattr(poller.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout='[{"pid":1,"parent_pid":2,"role":"mailbox","CommandLine":"SECRET"},{"pid":3,"parent_pid":2,"role":"unknown"}]'))
    assert poller._mailbox_process_diagnostics() == [{"pid": 1, "parent_pid": 2, "role": "mailbox"}]


def test_duplicate_poller_waits_for_owner_instead_of_exiting(monkeypatch, tmp_path):
    from local_agent import poller
    owner = object()
    attempts = []
    waits = []
    def acquire(path):
        attempts.append(path)
        if len(attempts) < 3:
            raise poller.PollerAlreadyRunning("busy")
        return owner
    monkeypatch.setattr(poller, "_acquire_instance_lock", acquire)
    monkeypatch.setattr(poller.time, "sleep", waits.append)
    assert poller._wait_for_instance_lock(tmp_path / "poller.lock") is owner
    assert waits == [10, 10]


def test_standby_poller_does_not_hide_unsafe_lock_path(monkeypatch, tmp_path):
    from local_agent import poller
    def acquire(path):
        raise RuntimeError("unsafe path")
    monkeypatch.setattr(poller, "_acquire_instance_lock", acquire)
    monkeypatch.setattr(poller.time, "sleep", lambda _: pytest.fail("unsafe error retried"))
    with pytest.raises(RuntimeError, match="unsafe path"):
        poller._wait_for_instance_lock(tmp_path / "poller.lock")


@pytest.fixture(autouse=True)
def _agent_interactive_console_for_tests(monkeypatch):
    # Simulate an interactive local terminal for approval-path unit tests.
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    # Legacy approval tests must be deterministic regardless of the developer's
    # real local Studio policy file. New unattended tests cover the opt-in path.
    from local_agent import poller
    from local_agent.mailbox_policy import default_policy
    monkeypatch.setattr(poller, "load_policy", default_policy)


def test_not_expired_accepts_future_utc_timestamp():
    future = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    assert _not_expired(SimpleNamespace(expires_at=future))


def test_not_expired_rejects_expired_timestamp():
    past = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    assert not _not_expired(SimpleNamespace(expires_at=past))


def test_not_expired_rejects_timestamp_without_timezone():
    assert not _not_expired(SimpleNamespace(expires_at="2026-10-09T12:00:00"))



def test_blender_preview_is_blocked_without_blender_install(monkeypatch):
    from local_agent import poller

    monkeypatch.delenv("BLENDER_EXECUTABLE", raising=False)
    monkeypatch.delenv("LOCAL_AGENT_WORKSPACE", raising=False)
    monkeypatch.setattr(poller, "find_blender_executable", lambda: None)
    result = poller._run_blender_forest_preview({"project_name": "mia"})
    assert result["status"] == "blocked"
    assert result["reason"] == "blender_executable_not_found"
    assert result["remote_paths_or_commands_accepted"] is False


def test_blender_preview_uses_local_default_workspace_when_unset(monkeypatch, tmp_path):
    from local_agent import poller
    import local_agent.blender_bridge as bridge_module

    calls = []
    class FakeBridge:
        def __init__(self, exe, workspace):
            calls.append((exe, workspace))
        def run_task(self, operation, **kwargs):
            calls.append((operation, kwargs))
            return {"status": "completed", "blend_path": "local-test"}

    monkeypatch.delenv("LOCAL_AGENT_WORKSPACE", raising=False)
    monkeypatch.setattr(poller, "ROOT", tmp_path / "BlenderStudio")
    monkeypatch.setattr(poller, "find_blender_executable", lambda: tmp_path / "blender.exe")
    monkeypatch.setattr(bridge_module, "BlenderBridge", FakeBridge)
    result = poller._run_blender_forest_preview({"project_name": "mia_test", "render": False})
    assert result["status"] == "completed"
    assert calls[0][1] == str(tmp_path / "AI-Agent-Workspace")
    assert calls[1][0] == "forest_preview"



def test_run_one_dispatches_blender_task_after_local_approval(monkeypatch):
    from local_agent import poller
    from types import SimpleNamespace

    future = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    task = SimpleNamespace(
        task_id="forest-002",
        operation="blender_forest_preview",
        expires_at=future,
        arguments={"project_name": "mia_forest"},
    )

    class FakeClient:
        published = None

        def fetch_desired_task(self):
            return task, "manifest-sha"

        def publish_result(self, task_id, result):
            self.published = (task_id, result)
            return "result-commit"

    client = FakeClient()
    monkeypatch.setattr("builtins.input", lambda prompt: "YES")
    monkeypatch.setattr(
        poller, "_run_blender_forest_preview",
        lambda arguments: {"status": "completed", "task": "blender_forest_preview"},
    )
    poller._run_one(client, task)
    assert client.published[0] == "forest-002"
    assert client.published[1]["status"] == "completed"



def test_run_one_rejects_same_id_if_task_changes_after_approval(monkeypatch):
    from local_agent import poller

    future = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    approved = SimpleNamespace(
        task_id="forest-003",
        operation="blender_forest_preview",
        expires_at=future,
        arguments={"project_name": "mia_forest"},
    )
    changed = SimpleNamespace(
        task_id="forest-003",
        operation="blender_forest_preview",
        expires_at=future,
        arguments={"project_name": "different_project"},
    )

    class FakeClient:
        published = None

        def fetch_desired_task(self):
            return changed, "new-manifest-sha"

        def publish_result(self, task_id, result):
            self.published = (task_id, result)
            return "result-commit"

    client = FakeClient()
    ran = []
    monkeypatch.setattr("builtins.input", lambda prompt: "YES")
    monkeypatch.setattr(poller, "_run_blender_forest_preview", lambda args: ran.append(args))
    poller._run_one(client, approved)
    assert ran == []
    assert client.published[1]["status"] == "superseded"
    assert client.published[1]["reason"] == "desired_task_changed_after_approval"


def test_run_one_rejects_task_that_expires_during_approval(monkeypatch):
    from local_agent import poller

    task = SimpleNamespace(
        task_id="forest-004",
        operation="blender_forest_preview",
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
        arguments={"project_name": "mia_forest"},
    )

    class FakeClient:
        published = None

        def fetch_desired_task(self):
            return task, "manifest-sha"

        def publish_result(self, task_id, result):
            self.published = (task_id, result)
            return "result-commit"

    client = FakeClient()
    ran = []
    def approve_but_expire(_prompt):
        task.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        return "YES"

    monkeypatch.setattr("builtins.input", approve_but_expire)
    monkeypatch.setattr(poller, "_run_blender_forest_preview", lambda args: ran.append(args))
    poller._run_one(client, task)
    assert ran == []
    assert client.published[1]["status"] == "rejected"
    assert client.published[1]["reason"] == "expired_while_waiting_for_local_approval"


def test_classify_manifest_detects_new_and_same_tasks():
    from local_agent.poller import classify_manifest
    assert classify_manifest({}, "task-1", "sha-1") == "new"
    state = {"last_task_id": "task-1", "manifest_sha": "sha-1"}
    assert classify_manifest(state, "task-1", "sha-1") == "same"
    assert classify_manifest(state, "task-2", "sha-2") == "new"


def test_classify_manifest_rejects_reused_task_id_with_changed_content():
    from local_agent.poller import classify_manifest
    state = {"last_task_id": "task-1", "manifest_sha": "sha-1"}
    assert classify_manifest(state, "task-1", "sha-2") == "reused_id"


def test_task_history_prevents_replay_after_a_newer_task(tmp_path):
    from local_agent.poller import _remember_manifest, classify_manifest
    state = {}
    state = _remember_manifest(state, "task-old", "sha-old")
    state = _remember_manifest(state, "task-new", "sha-new")
    assert classify_manifest(state, "task-old", "sha-old") == "same"


def test_rejected_changed_manifest_is_not_rejected_repeatedly():
    from local_agent.poller import _remember_manifest, classify_manifest
    state = _remember_manifest({}, "task-1", "sha-original")
    assert classify_manifest(state, "task-1", "sha-changed") == "reused_id"
    state = _remember_manifest(state, "task-1", "sha-changed", rejected=True)
    assert classify_manifest(state, "task-1", "sha-changed") == "same"
    assert classify_manifest(state, "task-1", "sha-another") == "reused_id"


def test_task_history_prevents_replay_after_a_newer_task(tmp_path):
    from local_agent.poller import _remember_manifest, classify_manifest
    state = {}
    state = _remember_manifest(state, "task-old", "sha-old")
    state = _remember_manifest(state, "task-new", "sha-new")
    assert classify_manifest(state, "task-old", "sha-old") == "same"


def test_rejected_changed_manifest_is_not_rejected_repeatedly():
    from local_agent.poller import _remember_manifest, classify_manifest
    state = _remember_manifest({}, "task-1", "sha-original")
    assert classify_manifest(state, "task-1", "sha-changed") == "reused_id"
    state = _remember_manifest(state, "task-1", "sha-changed", rejected=True)
    assert classify_manifest(state, "task-1", "sha-changed") == "same"
    assert classify_manifest(state, "task-1", "sha-another") == "reused_id"


def test_in_progress_manifest_is_not_new_after_restart():
    from local_agent.poller import _remember_manifest, classify_manifest
    state = _remember_manifest({}, "claimed-1", "sha-1", status="in_progress")
    assert state["processed_tasks"]["claimed-1"]["status"] == "in_progress"
    assert classify_manifest(state, "claimed-1", "sha-1") == "same"
    state = _remember_manifest(state, "claimed-1", "sha-1", status="interrupted")
    assert state["processed_tasks"]["claimed-1"]["status"] == "interrupted"


def test_poller_single_instance_lock_rejects_second_owner(tmp_path):
    import pytest
    from local_agent.poller import _acquire_instance_lock
    lock_path = tmp_path / "poller.lock"
    first = _acquire_instance_lock(lock_path)
    try:
        with pytest.raises(RuntimeError, match="already running"):
            _acquire_instance_lock(lock_path)
    finally:
        first.close()
    second = _acquire_instance_lock(lock_path)
    second.close()


def test_run_one_rejects_same_envelope_when_manifest_revision_changes(monkeypatch):
    from local_agent import poller
    future = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    task = SimpleNamespace(
        task_id="forest-005",
        operation="blender_forest_preview",
        expires_at=future,
        arguments={"project_name": "mia_forest"},
    )
    class FakeClient:
        published = None
        def fetch_desired_task(self):
            return task, "new-manifest-sha"
        def publish_result(self, task_id, result):
            self.published = (task_id, result)
            return "result-commit"
    client = FakeClient()
    ran = []
    monkeypatch.setattr("builtins.input", lambda _prompt: "YES")
    monkeypatch.setattr(poller, "_run_blender_forest_preview", lambda args: ran.append(args))
    poller._run_one(client, task, expected_manifest_sha="original-manifest-sha")
    assert ran == []
    assert client.published[1]["status"] == "superseded"
    assert client.published[1]["reason"] == "desired_task_changed_after_approval"


def test_remote_approval_is_blocked_even_with_local_opt_in(monkeypatch):
    from local_agent import poller
    future = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    task = SimpleNamespace(
        task_id="remote-forest-006",
        operation="blender_forest_preview",
        expires_at=future,
        requires_local_approval=False,
        arguments={"project_name": "mia_remote"},
    )
    class FakeClient:
        published = None
        def fetch_desired_task(self):
            return task, "manifest-sha"
        def publish_result(self, task_id, result):
            self.published = (task_id, result)
            return "result-commit"
    client = FakeClient()
    monkeypatch.setenv("LOCAL_AGENT_ALLOW_REMOTE_APPROVAL", "1")
    monkeypatch.setattr("builtins.input", lambda _prompt: (_ for _ in ()).throw(AssertionError("must not prompt")))
    ran = []
    monkeypatch.setattr(poller, "_run_blender_forest_preview", lambda args: ran.append(args) or {"status": "completed"})
    poller._run_one(client, task, expected_manifest_sha="manifest-sha")
    assert ran == []
    assert client.published[1]["status"] == "blocked"
    assert client.published[1]["reason"] == "remote_approval_disabled"


def test_remote_approval_fails_closed_without_local_opt_in(monkeypatch):
    from local_agent import poller
    future = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    task = SimpleNamespace(
        task_id="remote-forest-007",
        operation="blender_forest_preview",
        expires_at=future,
        requires_local_approval=False,
        arguments={"project_name": "mia_remote"},
    )
    class FakeClient:
        published = None
        def publish_result(self, task_id, result):
            self.published = (task_id, result)
            return "result-commit"
    client = FakeClient()
    monkeypatch.delenv("LOCAL_AGENT_ALLOW_REMOTE_APPROVAL", raising=False)
    ran = []
    monkeypatch.setattr(poller, "_run_blender_forest_preview", lambda args: ran.append(args))
    poller._run_one(client, task)
    assert ran == []
    assert client.published[1]["status"] == "blocked"
    assert client.published[1]["reason"] == "remote_approval_disabled"


def test_local_approval_task_is_blocked_without_interactive_console(monkeypatch):
    from local_agent import poller
    future = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    task = SimpleNamespace(
        task_id="console-required-008",
        operation="blender_forest_preview",
        expires_at=future,
        requires_local_approval=True,
        arguments={"project_name": "mia_console"},
    )
    class FakeClient:
        published = None
        def publish_result(self, task_id, result):
            self.published = (task_id, result)
            return "result-commit"
    client = FakeClient()
    monkeypatch.setattr(poller, "sys", SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: False)))
    monkeypatch.setattr("builtins.input", lambda _prompt: (_ for _ in ()).throw(AssertionError("must not prompt")))
    ran = []
    monkeypatch.setattr(poller, "_run_blender_forest_preview", lambda args: ran.append(args))
    poller._run_one(client, task)
    assert ran == []
    assert client.published[1]["status"] == "blocked"
    assert client.published[1]["reason"] == "local_console_approval_required_but_no_interactive_console"


def test_failed_task_writes_report_and_notifies_user(monkeypatch, tmp_path):
    from local_agent import poller
    from types import SimpleNamespace

    future = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    task = SimpleNamespace(
        task_id="diagnostic-fail-104",
        operation="doctor",
        expires_at=future,
        arguments={},
        requires_local_approval=True,
    )

    class FakeClient:
        published = None

        def fetch_desired_task(self):
            return task, "manifest-sha"

        def publish_result(self, task_id, result):
            self.published = (task_id, result)
            return "result-commit"

    client = FakeClient()
    report = tmp_path / "report.json"
    notifications = []
    monkeypatch.setattr("builtins.input", lambda prompt: "YES")
    monkeypatch.setitem(poller.SUPPORTED_HANDLERS, "doctor", lambda: {"status": "failed", "reason": "test_failure"})
    monkeypatch.setattr(poller, "write_report", lambda *args, **kwargs: report)
    monkeypatch.setattr(poller, "notify_user", lambda **kwargs: notifications.append(kwargs) or True)

    poller._run_one(client, task, "manifest-sha")

    assert client.published[0] == task.task_id
    assert client.published[1]["status"] == "failed"
    assert client.published[1]["local_report_path"].endswith("report.json")
    assert len(notifications) == 1
    assert task.task_id in notifications[0]["title"]
    assert ".local_agent/reports" in notifications[0]["message"]


def test_report_survives_github_publication_failure(monkeypatch, tmp_path):
    from local_agent import poller
    from local_agent.github_queue import QueueTransportError
    from types import SimpleNamespace

    future = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    task = SimpleNamespace(
        task_id="diagnostic-fail-105",
        operation="doctor",
        expires_at=future,
        arguments={},
        requires_local_approval=True,
    )

    class FakeClient:
        def fetch_desired_task(self):
            return task, "manifest-sha"

        def publish_result(self, task_id, result):
            raise QueueTransportError("network unavailable")

    report = tmp_path / "retained-report.json"
    monkeypatch.setattr("builtins.input", lambda prompt: "YES")
    monkeypatch.setitem(poller.SUPPORTED_HANDLERS, "doctor", lambda: {"status": "failed", "reason": "test_failure"})
    monkeypatch.setattr(poller, "write_report", lambda *args, **kwargs: report)
    monkeypatch.setattr(poller, "notify_user", lambda **kwargs: True)
    from local_agent.result_outbox import ResultOutbox
    monkeypatch.setattr(poller, "_result_outbox", lambda: ResultOutbox(tmp_path / "outbox"))

    poller._run_one(FakeClient(), task, "manifest-sha")

    # Both the local report and the unpublished task result survive the outage.
    assert report.parent == tmp_path
    pending = tmp_path / "outbox" / f"{task.task_id}.json"
    assert pending.is_file()

    class OnlineClient:
        published = []

        def publish_result(self, task_id, result):
            self.published.append((task_id, result))
            return "recovered-result-commit"

    online = OnlineClient()
    assert poller._result_outbox().flush(online)["published"] == 1
    assert online.published[0][0] == task.task_id
    assert not pending.exists()


def test_apply_patch_uses_isolated_worktree_and_never_changes_active_checkout(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import sys
    from local_agent import poller

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    monkeypatch.setattr(poller, "ROOT", root)
    monkeypatch.setattr(poller, "test_command", lambda suite, root: [sys.executable, "-m", "pytest", "-q", "tests/test_poller.py"])
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "git":
            if args[1:3] == ["rev-parse", "--verify"]:
                return SimpleNamespace(returncode=0, stdout="base-sha\n", stderr="")
            if args[1:4] == ["show-ref", "--verify", "--quiet"]:
                return SimpleNamespace(returncode=1, stdout="", stderr="")
            if args[1:3] == ["worktree", "add"]:
                from pathlib import Path
                Path(args[5]).mkdir(parents=True)
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if args[1:3] in (["apply", "--check"], ["apply"]):
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        assert args[:3] == [sys.executable, "-m", "pytest"]
        return SimpleNamespace(returncode=0, stdout="2 passed", stderr="")

    monkeypatch.setattr(poller.subprocess, "run", fake_run)
    result = poller._apply_patch("diff --git a/local_agent/a b/local_agent/a\n", "task-104")

    assert result["status"] == "completed"
    assert result["active_checkout_modified"] is False
    assert result["requires_review_before_merge"] is True
    assert result["base_commit"] == "base-sha"
    assert any(call[0][1:3] == ["worktree", "add"] for call in calls)
    assert any(call[0][:3] == [sys.executable, "-m", "pytest"] for call in calls)


def test_apply_patch_removes_temporary_worktree_when_post_patch_tests_fail(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import sys
    from local_agent import poller

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    monkeypatch.setattr(poller, "ROOT", root)
    monkeypatch.setattr(poller, "test_command", lambda suite, root: [sys.executable, "-m", "pytest", "-q", "tests/test_poller.py"])
    calls = []
    created_worktree = None

    def fake_run(args, **kwargs):
        nonlocal created_worktree
        calls.append(args)
        if args[0] == "git":
            if args[1:3] == ["rev-parse", "--verify"]:
                return SimpleNamespace(returncode=0, stdout="base-sha\n", stderr="")
            if args[1:4] == ["show-ref", "--verify", "--quiet"]:
                return SimpleNamespace(returncode=1, stdout="", stderr="")
            if args[1:3] == ["worktree", "add"]:
                from pathlib import Path
                created_worktree = Path(args[5])
                created_worktree.mkdir(parents=True)
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if args[1:3] == ["worktree", "remove"]:
                created_worktree.rmdir()
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if args[1:3] == ["branch", "-D"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        assert args[:3] == [sys.executable, "-m", "pytest"]
        return SimpleNamespace(returncode=1, stdout="1 failed", stderr="failure details")

    monkeypatch.setattr(poller.subprocess, "run", fake_run)
    result = poller._apply_patch("diff --git a/local_agent/a b/local_agent/a\n", "task-105")

    assert result["status"] == "failed_rolled_back"
    assert result["rollback_verified"] is True
    assert result["temporary_worktree_removed"] is True
    assert result["temporary_branch_removed"] is True
    assert created_worktree is not None and not created_worktree.exists()


def test_apply_patch_rejects_disallowed_paths_before_git_operations(tmp_path, monkeypatch):
    from local_agent import poller

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    monkeypatch.setattr(poller, "ROOT", root)
    result = poller._apply_patch(
        "diff --git a/tests/.git/config b/tests/.git/config\n", "unsafe-patch"
    )
    assert result == {"status": "rejected", "reason": "unsafe_or_malformed_patch"}
    assert not (tmp_path / ".local_agent_worktrees").exists()


def test_apply_patch_cleans_up_when_git_operation_times_out(tmp_path, monkeypatch):
    from local_agent import poller
    from types import SimpleNamespace
    import subprocess

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    monkeypatch.setattr(poller, "ROOT", root)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["rev-parse", "--verify"]:
            return SimpleNamespace(returncode=0, stdout="base-sha\n", stderr="")
        if args[1:4] == ["show-ref", "--verify", "--quiet"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if args[1:3] == ["worktree", "add"]:
            from pathlib import Path
            Path(args[5]).mkdir(parents=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[1:3] == ["apply", "--check"]:
            raise subprocess.TimeoutExpired(cmd=args, timeout=60)
        if args[1:3] == ["worktree", "remove"]:
            from pathlib import Path
            Path(args[4]).rmdir()
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[1:3] == ["branch", "-D"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(args)

    monkeypatch.setattr(poller.subprocess, "run", fake_run)
    result = poller._apply_patch("diff --git a/local_agent/file.py b/local_agent/file.py\n", "timeout-01")

    assert result["status"] == "timeout"
    assert result["rollback_verified"] is True
    assert result["temporary_worktree_removed"] is True
    assert result["temporary_branch_removed"] is True
    assert any(args[1:3] == ["worktree", "remove"] for args in calls)


def test_cleanup_preserves_branch_when_worktree_removal_fails(tmp_path):
    from local_agent import poller
    from types import SimpleNamespace

    calls = []
    def fake_git(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1, stderr="worktree busy", stdout="")

    result = poller._discard_failed_worktree(
        fake_git, tmp_path / "worktree", "agent/task-test",
        {"status": "failed_rolled_back", "reason": "post_patch_tests_failed"},
    )
    assert result["status"] == "failed_needs_user"
    assert result["reason"] == "failed_task_worktree_removal"
    assert not any(args[:2] == ["branch", "-D"] for args in calls)


def test_cleanup_reports_interruptions_instead_of_raising(tmp_path):
    from local_agent import poller
    import subprocess

    def fake_git(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=60)

    result = poller._discard_failed_worktree(
        fake_git, tmp_path / "worktree", "agent/task-test",
        {"status": "failed_rolled_back", "reason": "post_patch_tests_failed"},
    )
    assert result["status"] == "failed_needs_user"
    assert result["reason"] == "failed_task_cleanup_interrupted"


def test_load_state_returns_empty_only_when_state_file_is_missing(tmp_path, monkeypatch):
    from local_agent import poller

    state_path = tmp_path / "missing.json"
    monkeypatch.setattr(poller, "STATE_PATH", state_path)
    assert poller._load_state() == {}


def test_load_state_fails_closed_on_corrupt_json(tmp_path, monkeypatch):
    import pytest
    from local_agent import poller

    state_path = tmp_path / "poller_state.json"
    state_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(poller, "STATE_PATH", state_path)
    with pytest.raises(RuntimeError, match="invalid JSON"):
        poller._load_state()


def test_load_state_fails_closed_on_non_object_json(tmp_path, monkeypatch):
    import pytest
    from local_agent import poller

    state_path = tmp_path / "poller_state.json"
    state_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(poller, "STATE_PATH", state_path)
    with pytest.raises(RuntimeError, match="JSON object"):
        poller._load_state()


def test_load_state_fails_closed_on_corrupt_replay_history(tmp_path, monkeypatch):
    import json
    import pytest
    from local_agent import poller

    state_path = tmp_path / "poller_state.json"
    state_path.write_text(json.dumps({"processed_tasks": {"task-1": {"status": "processed"}}}), encoding="utf-8")
    monkeypatch.setattr(poller, "STATE_PATH", state_path)
    with pytest.raises(RuntimeError, match="replay history"):
        poller._load_state()



def test_run_one_redacts_sensitive_arguments_from_console(monkeypatch, capsys, tmp_path):
    from local_agent import poller
    from types import SimpleNamespace
    from datetime import datetime, timedelta, timezone

    future = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    task = SimpleNamespace(
        task_id="doctor-redaction-001",
        operation="doctor",
        expires_at=future,
        arguments={"github_token": "ghp_test_secret_do_not_log"},
        requires_local_approval=True,
    )

    class FakeClient:
        def fetch_desired_task(self):
            return task, "manifest-sha"

        def publish_result(self, task_id, result):
            return "result-commit"

    monkeypatch.setattr("builtins.input", lambda prompt: "YES")
    monkeypatch.setitem(poller.SUPPORTED_HANDLERS, "doctor", lambda: {"status": "completed"})
    monkeypatch.setattr(poller, "write_report", lambda *args, **kwargs: tmp_path / "report.json")

    poller._run_one(FakeClient(), task, "manifest-sha")

    output = capsys.readouterr().out
    assert "ghp_test_secret_do_not_log" not in output
    assert "[REDACTED]" in output


def test_not_expired_rejects_task_created_too_far_in_the_future():
    future_created = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    future_expiry = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
    assert not _not_expired(SimpleNamespace(created_at=future_created, expires_at=future_expiry))


def test_load_state_rejects_symlink_to_external_file(tmp_path, monkeypatch):
    import pytest
    from local_agent import poller

    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    state_path = tmp_path / "poller_state.json"
    try:
        state_path.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")
    monkeypatch.setattr(poller, "STATE_PATH", state_path)

    with pytest.raises(RuntimeError, match="must not be a symlink"):
        poller._load_state()
    assert outside.read_text(encoding="utf-8") == "{}"


def test_save_state_refuses_symlink_target(tmp_path, monkeypatch):
    import pytest
    from local_agent import poller

    outside = tmp_path / "outside.json"
    outside.write_text("preserve", encoding="utf-8")
    state_path = tmp_path / "poller_state.json"
    try:
        state_path.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")
    monkeypatch.setattr(poller, "STATE_PATH", state_path)

    with pytest.raises(RuntimeError, match="must not be a symlink"):
        poller._save_state({"processed_tasks": {}})
    assert outside.read_text(encoding="utf-8") == "preserve"


def test_poller_lock_refuses_symlink_target(tmp_path):
    import pytest
    from local_agent.poller import _acquire_instance_lock

    outside = tmp_path / "outside.lock"
    outside.write_text("preserve", encoding="utf-8")
    lock_path = tmp_path / "poller.lock"
    try:
        lock_path.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    with pytest.raises(RuntimeError, match="must not be a symlink"):
        _acquire_instance_lock(lock_path)
    assert outside.read_text(encoding="utf-8") == "preserve"


def test_agent_state_directory_rejects_symlink_escape(tmp_path, monkeypatch):
    import pytest
    from local_agent import poller

    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / ".local_agent").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")
    monkeypatch.setattr(poller, "ROOT", root)

    with pytest.raises(RuntimeError, match="must not be a symlink"):
        poller._ensure_agent_dir()


def test_github_mailbox_poller_is_opt_in(monkeypatch, capsys):
    from local_agent import poller
    monkeypatch.delenv("LOCAL_AGENT_ENABLE_GITHUB_MAILBOX", raising=False)
    assert poller.main() == 2
    assert "GitHub mailbox polling is disabled" in capsys.readouterr().out


def test_task_replay_history_survives_more_than_two_hundred_new_ids_and_restart(tmp_path, monkeypatch):
    from local_agent import poller

    first_id = "original-task"
    state = poller._remember_manifest({}, first_id, "original-manifest", status="processed")
    for index in range(220):
        state = poller._remember_manifest(state, f"subsequent-task-{index}", f"sha-{index}")

    path = tmp_path / "poller_state.json"
    monkeypatch.setattr(poller, "STATE_PATH", path)
    poller._save_state(state)
    restored = poller._load_state()
    assert len(restored["processed_tasks"]) == 221
    assert poller.classify_manifest(restored, first_id, "original-manifest") == "same"
    assert poller.classify_manifest(restored, first_id, "changed-manifest") == "reused_id"


def test_task_replay_history_fails_closed_at_capacity():
    from local_agent import poller

    state = {"processed_tasks": {
        f"old-task-{index}": {"manifest_sha": f"sha-{index}"}
        for index in range(10_000)
    }}
    with pytest.raises(RuntimeError, match="capacity"):
        poller._remember_manifest(state, "additional-task", "another-sha")
    assert "old-task-0" in state["processed_tasks"]
    assert "additional-task" not in state["processed_tasks"]


def test_load_state_rejects_incomplete_repair_history(tmp_path, monkeypatch):
    import json
    from local_agent import poller

    path = tmp_path / "poller_state.json"
    path.write_text(json.dumps({
        "processed_tasks": {},
        "processed_repairs": {"repair-1": {"status": "completed"}},
    }), encoding="utf-8")
    monkeypatch.setattr(poller, "STATE_PATH", path)
    with pytest.raises(RuntimeError, match="repair replay history"):
        poller._load_state()


def test_load_state_rejects_oversized_task_replay_history(tmp_path, monkeypatch):
    import json
    from local_agent import poller

    path = tmp_path / "poller_state.json"
    path.write_text(json.dumps({"processed_tasks": {
        f"old-{index}": {"manifest_sha": f"sha-{index}"}
        for index in range(10_001)
    }}), encoding="utf-8")
    monkeypatch.setattr(poller, "STATE_PATH", path)
    with pytest.raises(RuntimeError, match="capacity"):
        poller._load_state()


def test_blockout_overwrite_retry_is_limited_to_fixed_episode1_release(monkeypatch):
    from local_agent import poller
    calls = []
    monkeypatch.setattr(
        "local_agent.blender_workflow.create_mia_blockout",
        lambda project_name, *, overwrite=False, duration_seconds=5, task_id=None:
            calls.append((project_name, overwrite, duration_seconds, task_id)) or {"status": "completed"},
    )
    assert poller._run_blender_mia_blockout({
        "project_name": "S01E01_SC01_RELEASE", "overwrite": True
    })["status"] == "completed"
    assert calls == [("S01E01_SC01_RELEASE", True, 5, None)]
    assert poller._run_blender_mia_blockout({
        "project_name": "S01E01_SC01_DRAFT", "overwrite": True
    })["status"] == "rejected"
    assert poller._run_blender_mia_blockout({
        "project_name": "S01E01_SC01_RELEASE", "overwrite": False
    })["status"] == "completed"
    assert calls[-1] == ("S01E01_SC01_RELEASE", False, 5, None)
    assert len(calls) == 2


def test_five_second_retry_options_pass_mailbox_protocol():
    import json
    from local_agent.control_protocol import parse_task, ProtocolError
    value = {"protocol_version": 1, "task_id": "five-second-retry",
             "operation": "blender_mia_blockout",
             "created_at": "2026-10-12T16:00:00Z", "expires_at": "2026-10-12T18:00:00Z",
             "requires_local_approval": True,
             "arguments": {"project_name": "S01E01_SC01_RELEASE", "duration_seconds": 5, "overwrite": True}}
    assert parse_task(json.dumps(value)).arguments == value["arguments"]
    for changes in ({"project_name": "different_project"}, {"duration_seconds": True},
                    {"duration_seconds": 60}, {"overwrite": "yes"},
                    {"allow_full_render": True}, {"command": "anything"}):
        changed = {**value, "arguments": {**value["arguments"], **changes}}
        with pytest.raises(ProtocolError):
            parse_task(json.dumps(changed))


def test_generated_rig_skips_mesh_without_a_bone_selection():
    import ast
    from local_agent.blender_workflow import _scene_script
    tree = ast.parse(_scene_script())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build_rig")
    # Execute the actual guard with Blender's string-only membership contract.
    guard = next(node for node in ast.walk(function) if isinstance(node, ast.If)
                 and any(isinstance(part, ast.Compare) and any(isinstance(op, ast.NotIn) for op in part.ops)
                         for part in ast.walk(node.test)))
    class Bones:
        def __contains__(self, key):
            if not isinstance(key, str):
                raise TypeError("Blender requires a bone name")
            return key == "head"
    data = SimpleNamespace(bones=Bones())
    expression = compile(ast.Expression(guard.test), "rig-guard", "eval")
    assert eval(expression, {"bone": None, "data": data}) is True
    assert eval(expression, {"bone": "missing", "data": data}) is True
    assert eval(expression, {"bone": "head", "data": data}) is False


def test_five_second_animation_reads_blender5_channelbag_curves():
    import ast
    from local_agent.blender_workflow import _episode1_animation_script
    tree = ast.parse(_episode1_animation_script())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "action_fcurves")
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "action-curves", "exec"), namespace)
    first, second = object(), object()
    modern = SimpleNamespace(layers=[SimpleNamespace(strips=[
        SimpleNamespace(channelbags=[SimpleNamespace(fcurves=[first]), SimpleNamespace(fcurves=[second])])])])
    curves = namespace["action_fcurves"]
    assert list(curves(modern)) == [first, second]
    assert list(curves(SimpleNamespace(fcurves=[first]))) == [first]
    assert list(curves(SimpleNamespace(layers=[]))) == []


def test_character_review_routes_to_separate_version_without_scene_overwrite(monkeypatch):
    from local_agent import blender_workflow as workflow
    seen = []
    monkeypatch.setattr(workflow, "create_reference_mia_model", lambda **kw: seen.append(kw) or {"status": "completed", "production_ready": False})
    result = workflow.create_mia_blockout("MIA_REFERENCE_REVIEW", task_id="review-001")
    assert result["production_ready"] is False
    assert seen == [{"task_id": "review-001"}]
    with pytest.raises(workflow.BlenderWorkflowError):
        workflow.create_mia_blockout("MIA_REFERENCE_REVIEW", overwrite=True)


def test_character_review_refuses_unsafe_output_identity():
    from local_agent import blender_workflow as workflow
    with pytest.raises(workflow.BlenderWorkflowError):
        workflow.create_reference_mia_model(task_id="../other")


def test_mouth_animation_preserves_original_mesh_scale():
    import ast
    from local_agent.blender_workflow import _episode1_animation_script
    function = next(node for node in ast.parse(_episode1_animation_script()).body
                    if isinstance(node, ast.FunctionDef) and node.name == "animate_mouth")
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "mouth-animation", "exec"), namespace)
    frames = []
    obj = SimpleNamespace(scale=(0.105, 0.025, 0.025))
    obj.keyframe_insert = lambda **kw: frames.append((kw["frame"], obj.scale))
    namespace["animate_mouth"](obj, [(10, 30)])
    assert all(scale[:2] == (0.105, 0.025) and 0 < scale[2] <= 0.025 for _, scale in frames)


def test_remote_restart_envelope_is_data_only_and_keeps_local_approval():
    import json
    from local_agent import poller, github_queue
    from local_agent.control_protocol import ProtocolError

    envelope = {
        "protocol_version": 1,
        "task_id": "codex-restart-20261012",
        "operation": "restart_agent",
        "created_at": "2026-10-12T16:00:00Z",
        "expires_at": "2026-10-12T16:10:00Z",
        "requires_local_approval": True,
        "arguments": {},
    }
    parsed = github_queue.parse_task(json.dumps(envelope))
    assert parsed.operation == "restart_agent"
    assert parsed.arguments == {}
    assert parsed.requires_local_approval is True

    envelope["arguments"] = {"command": "anything"}
    with pytest.raises(ProtocolError, match="no arguments"):
        github_queue.parse_task(json.dumps(envelope))

    envelope["arguments"] = {}
    envelope["requires_local_approval"] = False
    with pytest.raises(ProtocolError, match="local approval"):
        github_queue.parse_task(json.dumps(envelope))


def test_remote_restart_needs_persistent_opt_in_or_local_launcher(monkeypatch):
    from local_agent import poller

    monkeypatch.delenv("LOCAL_AGENT_ALLOW_REMOTE_RESTART", raising=False)
    monkeypatch.setattr(poller, "get_opt_in", lambda: {"enabled": False})
    assert poller._remote_restart_enabled() is False

    monkeypatch.setattr(poller, "get_opt_in", lambda: {"enabled": True})
    assert poller._remote_restart_enabled() is True

    monkeypatch.setenv("LOCAL_AGENT_ALLOW_REMOTE_RESTART", "0")
    assert poller._remote_restart_enabled() is False


def test_remote_restart_opens_only_fixed_loopback_studio(monkeypatch):
    from local_agent import poller

    opened = []
    monkeypatch.setenv("LOCAL_AGENT_STUDIO_PORT", "55313")
    monkeypatch.setattr(poller, "request_runtime_restart", lambda _: {"restart_pending": True})
    monkeypatch.setattr(
        poller.webbrowser, "open",
        lambda url, new=0, autoraise=True: opened.append((url, new, autoraise)) or True,
    )
    result = poller._request_restart_and_open_studio()
    assert result["restart_pending"] is True
    assert result["browser_open_requested"] is True
    assert opened == [("http://127.0.0.1:55313/", 2, True)]

    monkeypatch.setenv("LOCAL_AGENT_STUDIO_PORT", "99999")
    poller._request_restart_and_open_studio()
    assert opened[-1][0] == "http://127.0.0.1:55313/"

def test_remote_blender_task_cancel_signal_is_scoped_to_active_task(tmp_path, monkeypatch):
    from local_agent import studio_jobs
    root = tmp_path / ".local_agent"
    monkeypatch.setattr(studio_jobs, "_AGENT_CONTROL_ROOT", root)
    monkeypatch.setattr(studio_jobs, "_AGENT_ACTIVE_TASK", root / "active_agent_task.json")
    monkeypatch.setattr(studio_jobs, "_AGENT_CANCEL_TASK", root / "cancel_agent_task.json")
    monkeypatch.setattr(studio_jobs, "_agent_control_dir", lambda: root.mkdir(parents=True, exist_ok=True) or root)
    active = studio_jobs.begin_agent_task("task-cancel-001", "blender_mia_blockout", "S01E01_SC01_RELEASE")
    assert active["state"] == "running"
    assert studio_jobs.agent_task_status()["state"] == "running"
    requested = studio_jobs.request_agent_task_cancel("task-cancel-001")
    assert requested["state"] == "cancelling"
    assert studio_jobs.agent_task_status()["state"] == "cancelling"
    assert studio_jobs.agent_task_cancel_requested("task-cancel-001")
    assert not studio_jobs.agent_task_cancel_requested("other-task")
    studio_jobs.finish_agent_task("task-cancel-001")
    assert studio_jobs.agent_task_status() == {"state": "idle"}


def test_cancelable_blender_process_stops_on_signal(monkeypatch, tmp_path):
    import sys
    from local_agent import blender_workflow
    seen = []
    monkeypatch.setattr(blender_workflow, "_agent_cancel_requested",
                        lambda task_id: seen.append(task_id) is None)
    completed, cancelled, timed_out, _extra, error_type = blender_workflow._run_cancellable_process(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        cwd=tmp_path, timeout=20, task_id="task-cancel-002",
    )
    assert cancelled and not timed_out and error_type is None
    assert completed.returncode is not None
    assert seen and set(seen) == {"task-cancel-002"}


# Direct Astra master-brief operation tests.
import base64 as _base64
import json as _json
import urllib.request as _urllib_request
from local_agent.control_protocol import ProtocolError as _ProtocolError

def _astra_task_envelope(operation="astra_season_response", arguments=None, approval=True):
    now=datetime.now(timezone.utc)
    return _json.dumps({"protocol_version":1,"task_id":"astra-response-test",
        "operation":operation,"created_at":now.isoformat(),
        "expires_at":(now+timedelta(hours=1)).isoformat(),
        "requires_local_approval":approval,"arguments":arguments or {}})

def test_astra_operation_uses_strict_envelope_and_no_arguments():
    from local_agent import poller
    task=poller._parse_task_with_restart(_astra_task_envelope())
    assert task.operation=="astra_season_response"
    with pytest.raises(_ProtocolError):
        poller._parse_task_with_restart(_astra_task_envelope(arguments={"prompt":"arbitrary"}))
    with pytest.raises(_ProtocolError):
        poller._parse_task_with_restart(_astra_task_envelope(approval=False))

def test_astra_response_reads_private_brief_uses_astra_and_checkpoints(tmp_path, monkeypatch):
    import local_agent.octava_credentials as credentials
    from local_agent import poller
    master="# MASTER WORK TASK\nFIRST MANDATORY END-TO-END TEST\n"+("details "*300)
    encoded=_base64.b64encode(master.encode()).decode()
    class GithubResponse:
        def json(self): return {"type":"file","encoding":"base64","content":encoded}
    class Client:
        def _request(self,method,path,**kwargs):
            assert method=="GET"
            assert path=="contents/private_tasks/octava_season30_master_20261013.txt"
            assert kwargs["params"]=={"ref":"main"}
            return GithubResponse()
    class ProviderResponse:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def read(self,limit):
            assert limit==180001
            return _json.dumps({"choices":[{"message":{"content":"Ответ Астры"}}]}).encode()
    captured={}
    def fake_urlopen(request,timeout):
        captured.update(request=request,timeout=timeout)
        return ProviderResponse()
    monkeypatch.setattr(poller,"load_policy",lambda:{"allow_octava":True})
    monkeypatch.setattr(credentials,"read_key",lambda:("local-test-key","windows_vault"))
    monkeypatch.setattr(_urllib_request,"urlopen",fake_urlopen)
    monkeypatch.setattr(poller,"_ensure_agent_dir",lambda:tmp_path)
    result=poller._run_astra_season_response(Client(),"astra-response-test")
    body=_json.loads(captured["request"].data)
    assert body["model"]=="gpt-6-astra"
    assert "MASTER WORK TASK" in body["messages"][1]["content"]
    assert captured["timeout"]==180
    assert result["status"]=="completed" and result["answer"]=="Ответ Астры"
    assert (tmp_path/"reports/astra-response-test_astra_response.txt").read_text()=="Ответ Астры"
    assert result["executed_commands"] is False

def test_astra_operation_stops_when_local_provider_consent_is_off(monkeypatch):
    from local_agent import poller
    monkeypatch.setattr(poller,"load_policy",lambda:{"allow_octava":False})
    class NoNetwork:
        def _request(self,*args,**kwargs): raise AssertionError("must stop before network")
    assert poller._run_astra_season_response(NoNetwork(),"astra-response-test")=={
        "status":"blocked","reason":"local_octava_permission_disabled"}

def test_luna_full_episode_operation_requires_fixed_no_argument_envelope():
    from local_agent import poller
    task=poller._parse_task_with_restart(_astra_task_envelope(
        operation="luna_s01e01_reference_test"))
    assert task.operation=="luna_s01e01_reference_test"
    assert task.operation in poller._SPECIALIZED_OPERATIONS
    with pytest.raises(_ProtocolError):
        poller._parse_task_with_restart(_astra_task_envelope(
            operation="luna_s01e01_reference_test",arguments={"prompt":"arbitrary"}))
    with pytest.raises(_ProtocolError):
        poller._parse_task_with_restart(_astra_task_envelope(
            operation="luna_s01e01_reference_test",approval=False))




def _mock_luna_season_import(monkeypatch, poller, raw=b"verified private season"):
    import hashlib
    from local_agent import studio_server

    source_sha = hashlib.sha256(raw).hexdigest()
    episode_ids = [f"S01E{number:02d}" for number in range(1, 31)]
    monkeypatch.setattr(poller, "_fetch_luna_season_source", lambda _client: raw)
    monkeypatch.setattr(studio_server, "import_season_screenplay", lambda _filename, _raw: {
        "source_sha256": source_sha, "episodes": 30,
    })
    monkeypatch.setattr(studio_server, "list_season_episodes", lambda: {
        "imported": True,
        "source_sha256": source_sha,
        "episodes": [{"episode_id": episode_id} for episode_id in episode_ids],
    })


def test_luna_full_episode_sends_complete_text_to_simple_model_and_validates_ids(monkeypatch, tmp_path):
    from local_agent import poller
    import local_agent.octava_credentials as credentials
    episode_text="S01E01 — Улитка на тропинке\n"+"Сцена с улиткой. "*800
    asset_ids=["char.snail_spiral.master","prop.leaf.master"]
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    monkeypatch.setattr(poller,"load_policy",lambda:{"allow_octava":True})
    monkeypatch.setattr(poller,"_ensure_agent_dir",lambda:tmp_path)
    _mock_luna_season_import(monkeypatch, poller)
    monkeypatch.setattr(credentials,"read_key",lambda:("local-test-key","windows_vault"))
    monkeypatch.setattr(credentials,"model_for_tier",lambda tier:"gpt-6-luna")
    monkeypatch.setattr("local_agent.studio_server.list_season_episodes",lambda:{
        "imported":True,
        "source_sha256":__import__("hashlib").sha256(b"verified private season").hexdigest(),
        "episodes":[{"episode_id":f"S01E{number:02d}"} for number in range(1,31)]})
    monkeypatch.setattr("local_agent.studio_server.get_season_episode",lambda episode_id:{
        "episode_id":episode_id,"full_text":episode_text,"asset_ids":asset_ids})
    monkeypatch.setattr("local_agent.asset_registry.read_asset_registry",lambda project,name:{
        asset_ids[0]:{"path":"assets/references/drafts/char.snail_spiral.master.jpg","extension":".jpg"}})
    class ProviderResponse:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def read(self,limit):
            return _json.dumps({"model":"gpt-6-luna","choices":[{"finish_reason":"stop",
                "message":{"content":_json.dumps({"required_asset_ids":asset_ids,
                    "selected_asset_id":asset_ids[0],"reason":"черновик",
                    "visual_brief":"Поворотная карточка персонажа"})}}],
                "usage":{"prompt_tokens":1400,"completion_tokens":80,"total_tokens":1480}}).encode()
    captured={}
    def fake_urlopen(request,timeout):
        captured["body"]=_json.loads(request.data)
        captured["timeout"]=timeout
        return ProviderResponse()
    monkeypatch.setattr("urllib.request.urlopen",fake_urlopen)
    result=poller._run_luna_s01e01_reference_test(object())
    sent=captured["body"]["messages"][1]["content"]
    assert captured["body"]["model"]=="gpt-6-luna"
    assert captured["body"]["max_tokens"]==700
    assert episode_text in sent
    assert "FULL IMPORTED S01E01 TEXT (complete, not summarized)" in sent
    assert result["status"]=="completed"
    assert result["decision"]["selected_asset_id"]==asset_ids[0]
    assert result["assets_seen"][0]["status"]=="draft"
    assert result["usage"]["total_tokens"]==1480
    assert result["image_generated"] is False


def test_luna_full_episode_blocks_when_simple_model_is_not_luna(monkeypatch, tmp_path):
    from local_agent import poller
    import local_agent.octava_credentials as credentials
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    monkeypatch.setattr(poller,"load_policy",lambda:{"allow_octava":True})
    _mock_luna_season_import(monkeypatch, poller)
    monkeypatch.setattr("local_agent.studio_server.list_season_episodes",lambda:{
        "imported":True,"source_sha256":__import__("hashlib").sha256(b"verified private season").hexdigest(),
        "episodes":[{"episode_id":f"S01E{number:02d}"} for number in range(1,31)]})
    monkeypatch.setattr("local_agent.studio_server.get_season_episode",lambda _: {
        "full_text":"S01E01 full text","asset_ids":["char.snail_spiral.master"]})
    monkeypatch.setattr("local_agent.asset_registry.read_asset_registry",lambda *_:{})
    monkeypatch.setattr(credentials,"read_key",lambda:("local-test-key","windows_vault"))
    monkeypatch.setattr(credentials,"model_for_tier",lambda tier:"other-model")
    assert poller._run_luna_s01e01_reference_test(object())["reason"]=="configured_simple_model_is_not_gpt_6_luna"



def test_luna_full_episode_blocks_on_private_source_failure_without_provider_call(monkeypatch, tmp_path):
    from local_agent import poller
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    monkeypatch.setattr(poller,"load_policy",lambda:{"allow_octava":True})
    monkeypatch.setattr(poller,"_fetch_luna_season_source",
                        lambda _client: (_ for _ in ()).throw(ValueError("source mismatch")))
    monkeypatch.setattr("local_agent.octava_credentials.read_key",
                        lambda: (_ for _ in ()).throw(AssertionError("must not call provider")))
    result=poller._run_luna_s01e01_reference_test(object())
    assert result=={"status":"blocked","reason":"private_screenplay_missing_or_changed"}



def test_pinned_source_item_requires_exact_path_size_and_git_blob_sha():
    import base64
    import hashlib
    from local_agent.poller import _decode_pinned_source_item

    raw = "UTF-8 screenplay".encode("utf-8")
    blob_sha = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    item = {
        "path": "private_tasks/script.txt",
        "sha": blob_sha,
        "size": len(raw),
        "encoding": "base64",
        "content": base64.b64encode(raw).decode("ascii"),
    }
    assert _decode_pinned_source_item(
        item, "private_tasks/script.txt", blob_sha, len(raw)
    ) == raw
    with pytest.raises(ValueError):
        _decode_pinned_source_item(
            item, "private_tasks/other.txt", blob_sha, len(raw)
        )
    with pytest.raises(ValueError):
        _decode_pinned_source_item(
            item, "private_tasks/script.txt", "0" * 40, len(raw)
        )


def test_season_parser_accepts_four_scenes_only_for_source_episode_26():
    from local_agent.studio_server import StudioError, _parse_episode_block

    def block(number, count):
        episode_id = f"S01E{number:02d}"
        scenes = "\n".join(
            f"## {episode_id}_SC{index:02d} | Сцена {index}"
            for index in range(1, count + 1)
        )
        return f"=== СЕРИЯ {number:02d} | Тест ===\nEPISODE_ID: {episode_id}\n{scenes}\n"

    assert len(_parse_episode_block(block(26, 4), 26)["scenes"]) == 4
    with pytest.raises(StudioError):
        _parse_episode_block(block(25, 4), 25)


def test_luna_image_model_preflight_reads_only_model_catalog(monkeypatch):
    from local_agent import poller
    import json as _json
    import local_agent.octava_credentials as credentials

    monkeypatch.setattr(poller, "load_policy", lambda: {"allow_octava": True})
    monkeypatch.setattr(credentials, "read_key", lambda: ("local-test-key", "windows_vault"))

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit):
            assert limit == 100_001
            return _json.dumps({"data": [
                {"id": "gpt-6-luna"},
                {"id": "gpt-image-1-mini"},
                {"id": "other"},
            ]}).encode()

    captured = {}
    def fake_urlopen(request, timeout):
        captured["method"] = request.method
        captured["url"] = request.full_url
        captured["data"] = request.data
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = poller._run_luna_image_model_preflight()
    assert result["status"] == "completed"
    assert result["request_method"] == "GET"
    assert result["generation_request_sent"] is False
    assert result["prompt_sent"] is False
    assert result["candidate_image_models"] == ["gpt-image-1-mini"]
    assert captured == {
        "method": "GET", "url": "https://octavapi.shop/v1/models",
        "data": None, "timeout": 20,
    }


def test_luna_image_model_preflight_does_not_call_provider_without_consent(monkeypatch):
    from local_agent import poller
    monkeypatch.setattr(poller, "load_policy", lambda: {"allow_octava": False})
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("provider must not be called")))
    assert poller._run_luna_image_model_preflight() == {
        "status": "blocked", "reason": "local_octava_permission_disabled"
    }


def test_save_season_asset_draft_registers_unique_local_draft(tmp_path):
    from types import SimpleNamespace
    from local_agent.studio_server import StudioError, save_season_asset_draft
    from local_agent.asset_registry import read_asset_registry

    workspace = tmp_path / "workspace"
    project = workspace / "mia_story"
    project.mkdir(parents=True)
    store = SimpleNamespace(workspace=workspace, project="mia_story", root=project)
    import struct
    import zlib
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    image_data = zlib.compress(b"\x00" * (1025 * 1024))
    raw = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">II5B", 1024, 1024, 8, 0, 0, 0, 0))
           + chunk(b"IDAT", image_data) + chunk(b"IEND", b""))
    result = save_season_asset_draft(store, "char.mia.master.luna_draft", raw, "png")
    assert result["path"] == "assets/references/drafts/char.mia.master.luna_draft.png"
    assert read_asset_registry(project, "mia_story")["char.mia.master.luna_draft"]["path"] == result["path"]
    assert (project / result["path"]).read_bytes() == raw
    with pytest.raises(StudioError):
        save_season_asset_draft(store, "char.mia.master.luna_draft", raw, "png")


def test_season_asset_library_includes_unreferenced_local_drafts(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from local_agent import studio_server

    store = SimpleNamespace(root=tmp_path, workspace=tmp_path.parent, project="mia_story")
    monkeypatch.setattr(studio_server, "list_season_episodes", lambda: {"episodes": []})
    monkeypatch.setattr("local_agent.asset_registry.read_asset_registry", lambda *_:{
        "char.mia.master.luna_draft":{"asset_id":"char.mia.master.luna_draft",
            "path":"assets/references/drafts/char.mia.master.luna_draft.png","extension":".png"}
    })
    result = studio_server.list_season_asset_library(store)
    assert result["assets"] == [{
        "asset_id":"char.mia.master.luna_draft","category":"characters","status":"draft",
        "image_url":"/api/asset-image/char.mia.master.luna_draft","review_status":"draft",
        "episodes":[],"scenes":[],
    }]


def test_rich_source_result_is_compacted_without_losing_goal_state(tmp_path,monkeypatch):
    from local_agent import poller
    from local_agent.result_outbox import ResultOutbox
    from local_agent.github_queue import MAX_RESULT_BYTES
    import json
    original={"task_id":"source-rich","status":"completed","local_report_path":"local/full.json",
              "details":{"identity_verified":False,"production_ready":False,"goal_status":"mia_likeness_not_accepted",
                         "blend_path":"local/mia.blend","thumbnail_jpeg_base64":{"front":"A"*12000,"face":"B"*12000,"side":"C"*25000,"back":"D"*25000},
                         "source_mesh_changes":[{"name":"mesh"+str(i),"coordinates":"x"*2000}for i in range(40)]}}
    summary=poller._bounded_result_summary(original)
    assert len(json.dumps(summary,ensure_ascii=False,indent=2).encode())<MAX_RESULT_BYTES
    assert summary["details"]["identity_verified"] is False
    assert summary["local_report_path"]=="local/full.json"
    assert len(original["details"]["source_mesh_changes"])==40
    monkeypatch.setattr(poller,"_result_outbox",lambda:ResultOutbox(tmp_path))
    class Client:
        def publish_result(self,task_id,result):
            assert result["result_compacted"] is True
            return "commit"
    assert poller._publish_result_durable(Client(),"source-rich",original)=="commit"


def test_legacy_mia_paths_cannot_reset_a_saved_source_target(monkeypatch,tmp_path):
    import json
    from local_agent import blender_workflow as workflow
    model=tmp_path/"SOURCE_ADAPTATIONS"/"source_latest"
    model.mkdir(parents=True)
    (model/"mia_spring_source_adapted.blend").write_bytes(b"saved native target")
    (model/"polish_report.json").write_text(json.dumps({"status":"completed"}))
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    monkeypatch.setattr(workflow,"find_blender_executable",lambda:pytest.fail("legacy generator must not launch"))
    for result in [workflow.create_reference_mia_model(task_id="new_review"),
                   workflow.run_mia_astra_autoloop_100(task_id="legacy_loop"),
                   workflow.run_mia_astra_autoloop_100_v2(task_id="legacy_loop2")]:
        assert result["status"]=="blocked"
        assert result["source_project"]=="source_latest"
        assert result["generation_performed"] is False
        assert result["provider_request_performed"] is False


def test_task_control_operations_are_typed_and_validated():
    import json
    from datetime import datetime, timedelta, timezone
    from local_agent import mailbox_policy
    from local_agent import github_queue
    from local_agent.control_protocol import ProtocolError
    mailbox_policy.install_task_control_parser()
    now = datetime.now(timezone.utc)
    base = {"protocol_version": 1, "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "requires_local_approval": True}
    for operation, args in (("stop_task", {}), ("resume_task", {"task_id": "original-task-01"}),
                            ("cancel_task", {"task_id": "original-task-01"})):
        task = github_queue.parse_task(json.dumps({**base, "task_id": "control-" + operation,
                                      "operation": operation, "arguments": args}))
        assert task.operation == operation and task.arguments == args
    for operation, args in (("stop_task", {"task_id": "x"}), ("resume_task", {}),
                            ("cancel_task", {"task_id": "../outside"})):
        with pytest.raises(ProtocolError):
            parse_task(json.dumps({**base, "task_id": "invalid-" + operation,
                                   "operation": operation, "arguments": args}))


def test_task_journal_preserves_exact_input_and_rejects_id_reuse(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from local_agent import mailbox_policy
    monkeypatch.setattr(mailbox_policy, "_ROOT", tmp_path)
    monkeypatch.setattr(mailbox_policy, "TASK_RUNS_DIR", tmp_path / ".local_agent" / "task_runs")
    now = datetime.now(timezone.utc)
    envelope = {"protocol_version": 1, "task_id": "journal-task-01", "operation": "doctor",
                "created_at": now.isoformat(), "expires_at": (now + timedelta(hours=1)).isoformat(),
                "requires_local_approval": True, "arguments": {}}
    journal = mailbox_policy.TaskJournal(envelope["task_id"])
    assert journal.directory == tmp_path / ".local_agent" / "task_runs" / envelope["task_id"]
    journal.save_input(envelope)
    journal.add_attempt({"number": 1, "status": "running", "started_at": mailbox_policy._task_now()})
    journal.finish_attempt(1, "interrupted", reason="operator_stop")
    assert journal.load_input()["envelope"] == envelope
    assert journal.state()["status"] == "interrupted"
    with pytest.raises(mailbox_policy.TaskJournalError, match="different input"):
        journal.save_input(dict(envelope, operation="status"))


def test_task_stop_flag_is_bound_to_live_task(tmp_path, monkeypatch):
    import os
    from local_agent import mailbox_policy
    monkeypatch.setattr(mailbox_policy, "_ROOT", tmp_path)
    monkeypatch.setattr(mailbox_policy, "TASK_RUNS_DIR", tmp_path / ".local_agent" / "task_runs")
    monkeypatch.setattr(mailbox_policy, "TASK_ACTIVE_FILE", tmp_path / ".local_agent" / "task_active.json")
    monkeypatch.setattr(mailbox_policy, "TASK_STOP_REQUEST", tmp_path / ".local_agent" / "task_stop_request.json")
    mailbox_policy._task_publish_active("active-task-01", os.getpid())
    assert mailbox_policy._task_request_stop()
    assert mailbox_policy._task_consume_stop("active-task-01")
    assert not mailbox_policy._task_consume_stop("active-task-01")
    mailbox_policy._task_clear_active("active-task-01")
    assert not mailbox_policy._task_request_stop()


def test_terminate_task_tree_stops_worker_process():
    import os
    import subprocess
    import sys
    from local_agent import mailbox_policy
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "shell": False}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
    mailbox_policy._task_terminate_tree(process)
    assert process.poll() is not None
