"""Regression tests for mailbox result delivery state."""
from local_agent.poller import _task_delivery_status


def test_pending_result_is_not_marked_processed() -> None:
    assert _task_delivery_status("task-123", {"task-123"}) == "pending_delivery"


def test_result_without_outbox_entry_is_marked_processed() -> None:
    assert _task_delivery_status("task-123", set()) == "processed"


def test_other_task_pending_does_not_block_this_task() -> None:
    assert _task_delivery_status("task-123", {"task-456"}) == "processed"


def test_reused_task_id_uses_distinct_stable_result_key():
    from local_agent.poller import _manifest_collision_result_id
    initial = _manifest_collision_result_id("task-original", "sha-new")
    assert initial == _manifest_collision_result_id("task-original", "sha-new")
    assert initial != _manifest_collision_result_id("task-original", "sha-other")
    assert initial != "task-original"
    assert len(initial) < 128
    assert "/" not in initial and "\\" not in initial


def test_main_preserves_original_result_when_task_id_is_reused(monkeypatch, tmp_path):
    import types

    from local_agent import poller
    from local_agent.result_outbox import ResultOutbox

    original = {"status": "completed", "video": "original.mp4"}
    remote_results = {"task-original": original}
    state = poller._remember_manifest({}, "task-original", "original-sha", status="processed")
    saved = []

    class FakeClient:
        def fetch_desired_task(self):
            return types.SimpleNamespace(task_id="task-original"), "changed-sha"

        def publish_result(self, task_id, result):
            if task_id in remote_results and remote_results[task_id] != result:
                raise AssertionError("attempted to overwrite immutable GitHub task result")
            remote_results[task_id] = result
            return "test-commit"

    class FakeLock:
        def close(self):
            pass

    client = FakeClient()
    monkeypatch.setenv("LOCAL_AGENT_ENABLE_GITHUB_MAILBOX", "1")
    monkeypatch.setattr(poller.QueueConfig, "from_environment", lambda: object())
    monkeypatch.setattr(poller, "GitHubQueueClient", lambda config: client)
    monkeypatch.setattr(poller, "_acquire_instance_lock", lambda path: FakeLock())
    monkeypatch.setattr(poller, "_load_state", lambda: state)
    monkeypatch.setattr(poller, "_save_state", lambda item: saved.append(item.copy()))
    monkeypatch.setattr(poller, "_result_outbox", lambda: ResultOutbox(tmp_path / "outbox"))
    monkeypatch.setattr(poller, "_poll_repair_once", lambda client, state: state)

    def stop_after_first_poll(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(poller.time, "sleep", stop_after_first_poll)

    assert poller.main() == 0
    assert remote_results["task-original"] == original
    distinct = [key for key in remote_results if key != "task-original"]
    assert len(distinct) == 1
    assert distinct[0].startswith("task-id-reuse-")
    assert remote_results[distinct[0]]["reason"] == "task_id_reused_with_different_manifest"
    assert saved[-1]["processed_tasks"]["task-original"]["manifest_sha"] == "original-sha"
    assert saved[-1]["processed_tasks"]["task-original"]["rejected_sha"] == "changed-sha"


def test_task_id_reuse_incident_survives_network_failure(monkeypatch, tmp_path):
    import types

    from local_agent import poller
    from local_agent.github_queue import QueueTransportError
    from local_agent.result_outbox import ResultOutbox

    state = poller._remember_manifest({}, "task-original", "original-sha")
    saved = []
    outbox = ResultOutbox(tmp_path / "outbox")

    class FakeClient:
        offline = True
        published = []

        def fetch_desired_task(self):
            return types.SimpleNamespace(task_id="task-original"), "changed-sha"

        def publish_result(self, task_id, result):
            if self.offline:
                raise QueueTransportError("offline")
            self.published.append((task_id, result))
            return "recovered-commit"

    class FakeLock:
        def close(self):
            pass

    client = FakeClient()
    monkeypatch.setenv("LOCAL_AGENT_ENABLE_GITHUB_MAILBOX", "1")
    monkeypatch.setattr(poller.QueueConfig, "from_environment", lambda: object())
    monkeypatch.setattr(poller, "GitHubQueueClient", lambda config: client)
    monkeypatch.setattr(poller, "_acquire_instance_lock", lambda path: FakeLock())
    monkeypatch.setattr(poller, "_load_state", lambda: state)
    monkeypatch.setattr(poller, "_save_state", lambda item: saved.append(item.copy()))
    monkeypatch.setattr(poller, "_result_outbox", lambda: outbox)
    monkeypatch.setattr(poller, "_poll_repair_once", lambda client, state: state)
    monkeypatch.setattr(poller.time, "sleep", lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()))

    assert poller.main() == 0
    incident_id = poller._manifest_collision_result_id("task-original", "changed-sha")
    assert incident_id in outbox.pending_task_ids()
    assert saved[-1]["processed_tasks"]["task-original"]["rejected_sha"] == "changed-sha"
    client.offline = False
    assert outbox.flush(client) == {"published": 1, "deferred": 0, "invalid": 0}
    assert incident_id not in outbox.pending_task_ids()
    assert client.published[0][0] == incident_id
