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
