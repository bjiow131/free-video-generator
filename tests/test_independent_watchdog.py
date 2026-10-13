from local_agent import poller
from types import SimpleNamespace
import json

def classify(**kw):
    default=dict(worker_alive=True,studio_alive=True,heartbeat_age=20,task_claimed=False,astra_checkpoint_age=None)
    default.update(kw);return poller._watchdog_classify(**default)

def test_dead_worker_reported_without_worker_cooperation():
    assert classify(worker_alive=False)=='agent_process_down'

def test_long_task_with_recent_checkpoint_is_not_false_crash():
    assert classify(heartbeat_age=1800,task_claimed=True,astra_checkpoint_age=120)=='no_detected_fault'

def test_stale_astra_progress_is_only_suspicion():
    assert classify(task_claimed=True,astra_checkpoint_age=601)=='astra_progress_stalled_suspected'

def test_idle_stale_loop_is_detected():
    assert classify(heartbeat_age=121)=='agent_loop_stalled_suspected'

def test_latest_health_write_uses_private_repo_and_observed_sha():
    calls=[]
    class Client:
        config=SimpleNamespace(ref='main')
        def _require_private_repo(self):calls.append('private')
        def _request(self,method,path,**kw):
            calls.append((method,path,kw));return SimpleNamespace(json=lambda:{'sha':'original'})
    reporter=poller._SupervisorHealthReporter(lambda:{})
    reporter.publish_latest(Client(),{'status':'agent_process_down'})
    assert calls[0]=='private'
    assert calls[-1][2]['json']['sha']=='original'

def test_failed_probe_never_claims_process_crash(monkeypatch):
    monkeypatch.setattr(poller,'_mailbox_process_diagnostics',lambda:[])
    assert poller._watchdog_process_snapshot()['status']=='process_probe_unavailable'

def test_watchdog_itself_is_not_mistaken_for_agent(monkeypatch):
    monkeypatch.setattr(poller,'_mailbox_process_diagnostics',lambda:[{'role':'watchdog'},{'role':'studio'}])
    monkeypatch.setattr(poller,'_load_state',lambda:{})
    assert poller._watchdog_process_snapshot()['status']=='agent_process_down'
