import ast
import re
import json
import os
from pathlib import Path
from typing import Any
from types import SimpleNamespace
import zipfile
import pytest

@pytest.fixture
def ns():
    tree=ast.parse((Path(__file__).resolve().parents[1]/'local_agent'/'poller.py').read_text())
    names={'_audit_safe_text','_audit_collect','_run_astra_project_audit','_astra_exchange_notification'}
    module=ast.Module(body=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name in names],type_ignores=[])
    result=dict(Path=Path,json=json,os=os,Any=Any,GitHubQueueClient=object,QueueTransportError=RuntimeError,re=re,_telegram_signal=lambda *args:None)
    exec(compile(module,'audit_helpers','exec'),result)
    return result

def test_secret_redaction(ns):
    s='api_key = "abcdefghijklmno"\nghp_'+'a'*32+'\nBearer '+'b'*32
    value=ns['_audit_safe_text'](s.encode())
    assert 'abcdefghijklmno' not in value and 'a'*32 not in value and 'b'*32 not in value

def test_unquoted_config_and_common_cloud_keys_are_redacted(ns):
    aws='AKIA'+'A'*16
    google='AIza'+'B'*35
    source=(f'api_key: unquoted-secret-value\npassword = another-secret # keep comment\n'
            f'cloud_key={aws}\nclient_key={google}\n')
    value=ns['_audit_safe_text'](source.encode())
    for secret in ('unquoted-secret-value','another-secret',aws,google):
        assert secret not in value
    assert '# keep comment' in value

def test_archive_scope_and_integrity(ns,tmp_path):
    root=tmp_path/'source';root.mkdir()
    (root/'app.py').write_text('print(1)')
    (root/'.env').write_text('API_KEY=secret')
    (root/'credentials.json').write_text('{"token":"secret"}')
    (root/'.local_agent').mkdir();(root/'.local_agent'/'state.json').write_text('secret')
    (root/'model.blend').write_bytes(b'BLENDER')
    (root/'link.py').symlink_to(root/'app.py')
    zip_path=tmp_path/'audit.zip'
    index,texts=ns['_audit_collect'](root,zip_path)
    assert set(texts)=={'app.py'}
    with zipfile.ZipFile(zip_path) as z:
        assert z.testzip() is None
        assert z.read('project/app.py')==b'print(1)'
        assert json.loads(z.read('FILE_INDEX.json'))==index

def test_non_utf8_excluded(ns,tmp_path):
    root=tmp_path/'source';root.mkdir();(root/'broken.py').write_bytes(b'\xff')
    index,texts=ns['_audit_collect'](root,tmp_path/'audit.zip')
    assert not texts and index[0]['status']=='excluded_non_utf8'

def test_size_limit_not_silent(ns,tmp_path):
    root=tmp_path/'source';root.mkdir();(root/'big.py').write_bytes(b'a'*500001)
    index,texts=ns['_audit_collect'](root,tmp_path/'audit.zip')
    assert not texts and index[0]['status']=='excluded_size_limit'

def test_no_archive_overwrite(ns,tmp_path):
    root=tmp_path/'source';root.mkdir();p=tmp_path/'audit.zip';p.write_bytes(b'original')
    with pytest.raises(FileExistsError):ns['_audit_collect'](root,p)
    assert p.read_bytes()==b'original'

def test_policy_blocks_before_io(ns):
    ns['load_policy']=lambda:{'allow_octava':False}
    assert ns['_run_astra_project_audit'](None,'id')['status']=='blocked'

def test_symlinked_reports_directory_is_rejected_before_network(ns,tmp_path,monkeypatch):
    agent_root=tmp_path/'state';agent_root.mkdir()
    reports=agent_root/'reports'
    monkeypatch.setattr(Path,'is_symlink',lambda path:path==reports)
    ns.update(load_policy=lambda:{'allow_octava':True},
              _ensure_agent_dir=lambda:agent_root)
    result=ns['_run_astra_project_audit'](None,'audit-id')
    assert result=={'status':'blocked','reason':'unsafe_audit_report_directory'}
    assert not (reports/'audit-id').exists()

def test_full_request_loop(ns,tmp_path,monkeypatch):
    import base64,sys,urllib.request
    root=tmp_path/'source';root.mkdir();(root/'app.py').write_text('print(1)')
    ns.update(ROOT=root,load_policy=lambda:{'allow_octava':True},_ensure_agent_dir=lambda:tmp_path/'state')
    monkeypatch.setitem(sys.modules,'local_agent.octava_credentials',SimpleNamespace(read_key=lambda:('fake',None)))
    calls=[]
    replies=['part notes',json.dumps({'file_requests':['app.py'],'reason':'review'}),json.dumps({'audit_report':'scope limited','work_prompt':'fix tests','file_requests':[]})]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return json.dumps({'model':'gpt-6-astra','choices':[{'message':{'content':replies.pop(0)},'finish_reason':'stop'}]}).encode()
    def urlopen(req,timeout):calls.append(json.loads(req.data));return Response()
    monkeypatch.setattr(urllib.request,'urlopen',urlopen)
    class Client:
        config=SimpleNamespace(ref='main')
        def _require_private_repo(self):pass
        def _request(self,method,path,**kw):
            if method=='PUT':return None
            return SimpleNamespace(json=lambda:{'content':base64.b64encode(b'a'*1001).decode()})
    result=ns['_run_astra_project_audit'](Client(),'audit-id')
    assert result['status']=='completed'
    assert result['zip_uploaded_to_provider'] is False
    assert result['full_project_audit_verified'] is False
    assert 'FILE app.py' in calls[-1]['messages'][1]['content']
    assert (tmp_path/'state/reports/audit-id/WORK_PROMPT.txt').read_text()=='fix tests'

def test_large_audit_reduces_saved_notes_before_final_synthesis(ns,tmp_path,monkeypatch):
    import base64,sys,urllib.request
    root=tmp_path/'source';root.mkdir()
    ns.update(ROOT=root,load_policy=lambda:{'allow_octava':True},_ensure_agent_dir=lambda:tmp_path/'state')
    def collect(root,archive):
        with zipfile.ZipFile(archive,'w'):
            pass
        return ([{'path':f'f{i}.py','status':'included'} for i in range(50)],{f'f{i}.py':'x'*45000 for i in range(50)})
    ns['_audit_collect']=collect
    monkeypatch.setitem(sys.modules,'local_agent.octava_credentials',SimpleNamespace(read_key=lambda:('fake',None)))
    calls=[]
    class Response:
        def __init__(self,answer):self.answer=answer
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return json.dumps({'model':'fake','choices':[{'message':{'content':self.answer},'finish_reason':'stop'}]}).encode()
    def urlopen(req,timeout):
        user=json.loads(req.data)['messages'][1]['content'];calls.append(user)
        if user.startswith('PART '): answer='N'*2000
        elif user.startswith('Synthesize this group'): answer='R'*5000
        else: answer=json.dumps({'audit_report':'report','work_prompt':'prompt','file_requests':[]})
        return Response(answer)
    monkeypatch.setattr(urllib.request,'urlopen',urlopen)
    class Client:
        config=SimpleNamespace(ref='main')
        def _require_private_repo(self):pass
        def _request(self,method,path,**kw):
            if method=='PUT':return None
            return SimpleNamespace(json=lambda:{'content':base64.b64encode(b'a'*1001).decode()})
    result=ns['_run_astra_project_audit'](Client(),'large-audit')
    assert result['status']=='completed'
    assert result['chunks_sent']==50
    assert any(x.startswith('Synthesize this group') for x in calls)
    assert calls[-1].startswith('SOURCE INDEX:')
    assert (tmp_path/'state/reports/large-audit/part_50.txt').read_text()=='N'*2000
    assert (tmp_path/'state/reports/large-audit/reduce_1_1.txt').exists()


def test_request_start_notification_is_not_delivery_claim(ns):
    events=[]
    ns['_telegram_signal']=lambda *args:events.append(args)
    ns['_astra_exchange_notification']('task','part_1','started','FILE app.py OFFSET 0\nsecret source')
    assert events[0][0]=='astra-started'
    assert 'Начинаю запрос к Астре' in events[0][2]
    assert 'Отправил задачу' not in events[0][2]
    assert 'app.py' in events[0][2]
    assert 'secret source' not in events[0][2]


def test_request_start_precedes_blocking_provider_call():
    source=(Path(__file__).resolve().parents[1]/'local_agent'/'poller.py').read_text()
    tree=ast.parse(source)
    audit=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='_run_astra_project_audit')
    ask=next(x for x in ast.walk(audit) if isinstance(x,ast.FunctionDef) and x.name=='ask')
    start=next(x for x in ast.walk(ask) if isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id=='_astra_exchange_notification' and any(isinstance(a,ast.Constant) and a.value=='started' for a in x.args))
    network=next(x for x in ast.walk(ask) if isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id=='urlopen')
    assert start.lineno < network.lineno
