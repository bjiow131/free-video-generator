import pytest
"""Crash/replay regressions for the reviewed GitHub repair channel."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from local_agent import poller


def _incoming(repair_id="repair-replay-01"):
    now = datetime.now(timezone.utc)
    return {
        "repair_id": repair_id,
        "created_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(minutes=10)).isoformat(),
        "base_commit_sha": "a" * 40,
    }, "manifest-sha", "diff --git a/tests/fix.py b/tests/fix.py\n"


def test_interrupted_repair_is_not_reexecuted_or_overwritten(monkeypatch):
    incoming = _incoming()
    state = {"processed_repairs": {
        incoming[0]["repair_id"]: {"manifest_sha": incoming[1], "status": "in_progress"}
    }}
    changes = []
    monkeypatch.setattr(poller, "fetch_repair", lambda client: incoming)
    monkeypatch.setattr(poller, "_save_state", lambda value: changes.append(value.copy()))
    monkeypatch.setattr(
        poller, "_apply_patch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("replayed an unknown-result repair")),
    )
    monkeypatch.setattr(
        poller, "_publish_result_durable",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("overwrote original result")),
    )

    updated = poller._poll_repair_once(object(), state)
    assert updated["processed_repairs"][incoming[0]["repair_id"]]["status"] == "interrupted"
    assert changes and changes[-1]["processed_repairs"][incoming[0]["repair_id"]]["status"] == "interrupted"


def test_reused_repair_id_preserves_original_claim(monkeypatch):
    incoming = _incoming()
    state = {"processed_repairs": {
        incoming[0]["repair_id"]: {"manifest_sha": "original-sha", "status": "completed"}
    }}
    monkeypatch.setattr(poller, "fetch_repair", lambda client: incoming)
    monkeypatch.setattr(
        poller, "_save_state",
        lambda *args: (_ for _ in ()).throw(AssertionError("replaced immutable repair history")),
    )
    monkeypatch.setattr(
        poller, "_publish_result_durable",
        lambda *args: (_ for _ in ()).throw(AssertionError("replaced immutable result")),
    )
    updated = poller._poll_repair_once(object(), state)
    assert updated["processed_repairs"][incoming[0]["repair_id"]] == {
        "manifest_sha": "original-sha", "status": "completed"
    }


def test_approved_repair_claim_saved_before_execution(monkeypatch):
    incoming = _incoming()
    repair_id = incoming[0]["repair_id"]
    snapshot = []
    reported = []

    def save_state(current):
        snapshot.append({
            key: dict(value) if isinstance(value, dict) else value
            for key, value in current.items()
        })

    def apply_patch(*args, **kwargs):
        assert snapshot
        assert snapshot[-1]["processed_repairs"][repair_id]["status"] == "in_progress"
        return {"status": "rejected", "reason": "intentional regression fixture"}

    monkeypatch.setattr(poller, "fetch_repair", lambda client: incoming)
    monkeypatch.setattr(poller, "_save_state", save_state)
    monkeypatch.setattr(poller, "_apply_patch", apply_patch)
    monkeypatch.setattr(poller, "_publish_result_durable",
                        lambda client, task_id, result: reported.append((task_id, result)))
    monkeypatch.setattr(poller.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="a" * 40))
    monkeypatch.setattr(poller.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda prompt: "YES")

    updated = poller._poll_repair_once(object(), {})
    assert len(snapshot) >= 2
    assert snapshot[0]["processed_repairs"][repair_id]["status"] == "in_progress"
    assert updated["processed_repairs"][repair_id]["status"] == "rejected"
    assert reported[0][0] == f"repair-{repair_id}"


def test_repair_history_survives_more_than_one_hundred_new_repairs(monkeypatch):
    from local_agent import poller

    class Reply:
        returncode = 0
        stdout = "wrong-base"

    manifest = {"repair_id": "repair-new-0", "base_commit_sha": "a" * 40}
    monkeypatch.setattr(poller, "fetch_repair", lambda _client: (
        dict(manifest), "new-sha", "diff --git a/tests/sample.py b/tests/sample.py\n",
    ))
    monkeypatch.setattr(poller.subprocess, "run", lambda *args, **kwargs: Reply())
    monkeypatch.setattr(poller, "_publish_result_durable", lambda *args: "recorded")
    monkeypatch.setattr(poller, "_save_state", lambda state: None)
    monkeypatch.setattr(
        poller, "_apply_patch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected code execution")),
    )
    original_id = "original-repair-id"
    state = {"processed_repairs": {
        original_id: {"manifest_sha": "original-sha", "status": "completed"}
    }}
    for i in range(120):
        manifest["repair_id"] = f"repair-new-{i}"
        state = poller._poll_repair_once(object(), state)
    assert len(state["processed_repairs"]) == 121
    assert state["processed_repairs"][original_id] == {
        "manifest_sha": "original-sha", "status": "completed",
    }
    manifest["repair_id"] = original_id
    unchanged = poller._poll_repair_once(object(), state)
    assert unchanged["processed_repairs"][original_id]["manifest_sha"] == "original-sha"


def test_repair_history_capacity_rejects_new_work_before_git_or_network(monkeypatch):
    from local_agent import poller

    manifest = {"repair_id": "fresh-repair", "base_commit_sha": "a" * 40}
    monkeypatch.setattr(poller, "fetch_repair", lambda _client: (
        manifest, "fresh-sha", "diff --git a/tests/sample.py b/tests/sample.py\n",
    ))
    monkeypatch.setattr(
        poller.subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Git must not run")),
    )
    monkeypatch.setattr(
        poller, "_publish_result_durable",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no output should be overwritten")),
    )
    state = {"processed_repairs": {
        f"repair-{i}": {"manifest_sha": f"sha-{i}", "status": "completed"}
        for i in range(2000)
    }}
    with pytest.raises(RuntimeError, match="capacity"):
        poller._poll_repair_once(object(), state)
    assert "repair-0" in state["processed_repairs"]
    assert "fresh-repair" not in state["processed_repairs"]
