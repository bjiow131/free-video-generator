"""Tests for poller expiry and task supersession helpers."""
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from local_agent.poller import _not_expired


def test_not_expired_accepts_future_utc_timestamp():
    future = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    assert _not_expired(SimpleNamespace(expires_at=future))


def test_not_expired_rejects_expired_timestamp():
    past = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    assert not _not_expired(SimpleNamespace(expires_at=past))


def test_not_expired_rejects_timestamp_without_timezone():
    assert not _not_expired(SimpleNamespace(expires_at="2026-10-09T12:00:00"))



def test_blender_preview_is_blocked_without_local_configuration(monkeypatch):
    from local_agent.poller import _run_blender_forest_preview

    monkeypatch.delenv("BLENDER_EXECUTABLE", raising=False)
    monkeypatch.delenv("LOCAL_AGENT_WORKSPACE", raising=False)
    result = _run_blender_forest_preview({"project_name": "mia"})
    assert result["status"] == "blocked"
    assert result["remote_paths_or_commands_accepted"] is False



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


def test_remote_approved_allowlisted_task_runs_without_console_prompt(monkeypatch):
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
    assert ran == [{"project_name": "mia_remote"}]
    assert client.published[1]["status"] == "completed"


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
    assert client.published[1]["reason"] == "remote_approval_not_enabled_or_operation_not_allowlisted"


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
    monkeypatch.setattr(poller.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _prompt: (_ for _ in ()).throw(AssertionError("must not prompt")))
    ran = []
    monkeypatch.setattr(poller, "_run_blender_forest_preview", lambda args: ran.append(args))
    poller._run_one(client, task)
    assert ran == []
    assert client.published[1]["status"] == "blocked"
    assert client.published[1]["reason"] == "local_console_approval_required_but_no_interactive_console"
