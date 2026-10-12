"""After owner's opt-out, ten-minute idle notices are never delivered."""
from __future__ import annotations
import hashlib
import json
from local_agent import poller, studio_server

def test_all_idle_intervals_and_offline_states_are_silent(monkeypatch):
    queued=[]
    monkeypatch.setattr(studio_server,"telegram_queue_event",lambda *args: queued.append(args) or True)
    monkeypatch.setattr(studio_server,"telegram_flush_outbox",lambda **kwargs: queued.append(kwargs) or 1)
    state=poller._mailbox_idle_initialize({},now=1000)
    for when in (1599,1600,2200,2800,4000,86400):
        assert poller._mailbox_idle_tick(state,github_reachable=True,now=when) is state
        assert poller._mailbox_idle_tick(state,github_reachable=False,now=when) is state
    assert queued==[]

def test_queued_old_idle_notices_are_purged_without_deleting_errors(monkeypatch,tmp_path):
    monkeypatch.setattr(poller,"ROOT",tmp_path)
    outbox=tmp_path/".local_agent"/"telegram_outbox"
    outbox.mkdir(parents=True)
    for name in ("mailbox-idle:old","task-error:new","service-restart:restart"):
        key=hashlib.sha256(name.encode()).hexdigest()+".json"
        (outbox/key).write_text(json.dumps({"event":name,"message":"test","timestamp":999}),encoding="utf-8")
    assert poller._purge_idle_telegram_outbox()==1
    remaining=[json.loads(f.read_text())["event"] for f in outbox.glob("*.json")]
    assert set(remaining)=={"task-error:new","service-restart:restart"}

def test_legacy_clock_still_loads_but_does_not_send():
    legacy={"mailbox_last_new_task_at":1000.0,"mailbox_idle_notice_sent":True}
    state=poller._mailbox_idle_initialize(legacy,now=1900)
    assert state["mailbox_idle_last_notice_at"]==1900
    assert poller._mailbox_idle_tick(state,github_reachable=True,now=2500) is state

def test_old_manifest_not_new_task():
    state={"last_task_id":"task-1","manifest_sha":"sha-1",
        "processed_tasks":{"task-1":{"manifest_sha":"sha-1"}}}
    idle=poller._mailbox_idle_new_task(state,now=1234)
    assert poller.classify_manifest(idle,"task-1","sha-1")=="same"
    assert poller.classify_manifest(idle,"task-2","sha-2")=="new"
