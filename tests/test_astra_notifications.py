from local_agent import poller
import json

def test_sent_summary_names_real_files(monkeypatch):
    events=[]
    monkeypatch.setattr(poller,'_telegram_signal',lambda *args:events.append(args))
    poller._astra_exchange_notification('task','part_1','sent','FILE local_agent/runner.py OFFSET 0\nprint(1)')
    assert 'Отправил задачу Астре' in events[0][2]
    assert 'local_agent/runner.py' in events[0][2]
    assert 'print(1)' not in events[0][2]

def test_received_file_requests_and_secret_redaction(monkeypatch):
    events=[];monkeypatch.setattr(poller,'_telegram_signal',lambda *args:events.append(args))
    poller._astra_exchange_notification('task','synthesis_1','received',json.dumps({'file_requests':['local_agent/runner.py']}))
    assert 'Запрошены файлы' in events[-1][2]
    poller._astra_exchange_notification('task','synthesis_2','received','Bearer '+'a'*32+' api_key="abcdefghi12345"')
    assert 'a'*32 not in events[-1][2]
    assert 'abcdefghi12345' not in events[-1][2]
    assert len(events[-1][2])<=600

def test_telegram_failure_cannot_break_model_task(monkeypatch):
    def fail(*args):raise RuntimeError('offline')
    monkeypatch.setattr(poller,'_telegram_signal',fail)
    poller._astra_exchange_notification('task','part_1','received','Actual answer')
