import ast
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
    names={'_audit_safe_text','_audit_collect','_run_astra_project_audit'}
    module=ast.Module(body=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name in names],type_ignores=[])
    result=dict(Path=Path,json=json,os=os,Any=Any,GitHubQueueClient=object,QueueTransportError=RuntimeError)
    exec(compile(module,'audit_helpers','exec'),result)
    return result

def test_secret_redaction(ns):
    s='api_key = "abcdefghijklmno"\nghp_'+'a'*32+'\nBearer '+'b'*32
    value=ns['_audit_safe_text'](s.encode())
    assert 'abcdefghijklmno' not in value and 'a'*32 not in value and 'b'*32 not in value

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
