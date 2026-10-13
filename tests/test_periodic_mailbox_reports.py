from types import SimpleNamespace
import json
from local_agent import poller

def test_ten_minute_interval():
    assert poller._PeriodicMailboxReporter.INTERVAL_SECONDS == 600

def test_active_task_and_idle_are_distinct(monkeypatch):
    monkeypatch.setattr(poller,'load_runtime_control',lambda:{'paused':False})
    reporter=poller._PeriodicMailboxReporter(None)
    assert reporter.snapshot()['worker_state']=='idle'
    reporter.begin(SimpleNamespace(task_id='task1',operation='astra_project_audit'))
    result=reporter.snapshot()
    assert result['worker_state']=='executing_task'
    assert result['active_task']['task_id']=='task1'
    reporter.finish()
    result=reporter.snapshot()
    assert result['worker_state']=='idle'
    assert 'handler_returned' in result['last_task']['state']
    assert 'completed' not in result['last_task']['state']

def test_only_allowlisted_numeric_progress_is_reported(monkeypatch,tmp_path):
    monkeypatch.setattr(poller,'ROOT',tmp_path)
    monkeypatch.setattr(poller,'load_runtime_control',lambda:{'paused':False})
    p=tmp_path/'.local_agent/reports/audit1/progress.json';p.parent.mkdir(parents=True)
    p.write_text(json.dumps({'chunks_sent':2,'source_chunks':8,'answer':'secret-text','token':'private-token','files_in_archive':True}))
    reporter=poller._PeriodicMailboxReporter(None)
    reporter.begin(SimpleNamespace(task_id='audit1',operation='astra_project_audit'))
    result=reporter.snapshot()
    assert result['active_task']['progress']=={'source_chunks':8,'chunks_sent':2}
    assert 'secret-text' not in json.dumps(result)
    assert 'private-token' not in json.dumps(result)

def test_durable_report_precedes_network_and_ids_are_unique(monkeypatch):
    monkeypatch.setattr(poller,'load_runtime_control',lambda:{'paused':False})
    rows=[]
    class Outbox:
        def enqueue(self,key,data): rows.append((key,data))
        def flush(self,client): raise RuntimeError('offline')
    reporter=poller._PeriodicMailboxReporter(None)
    import pytest
    with pytest.raises(RuntimeError):reporter.emit(None,Outbox())
    with pytest.raises(RuntimeError):reporter.emit(None,Outbox())
    assert len(rows)==2 and rows[0][0]!=rows[1][0]

def test_reporter_has_independent_transport_and_waits_600_seconds(monkeypatch,tmp_path):
    client=object();events=[]
    monkeypatch.setattr(poller,'GitHubQueueClient',lambda config:client)
    monkeypatch.setattr(poller,'_ensure_agent_dir',lambda:tmp_path)
    monkeypatch.setattr(poller,'ResultOutbox',lambda path:object())
    reporter=poller._PeriodicMailboxReporter(None)
    monkeypatch.setattr(reporter,'emit',lambda c,o:events.append(c))
    class Stop:
        def is_set(self):return False
        def wait(self,interval):events.append(interval);return True
    reporter.stop_event=Stop();reporter.run()
    assert events==[client,600]
