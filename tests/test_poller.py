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
