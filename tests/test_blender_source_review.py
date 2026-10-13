import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from local_agent import blender_rigging as r
from local_agent.control_protocol import parse_task, ProtocolError

def envelope(args):
 return json.dumps({'protocol_version':1,'task_id':'source-test','operation':'blender_source_review','created_at':'2026-10-13T22:00:00Z','expires_at':'2026-10-14T22:00:00Z','requires_local_approval':True,'arguments':args})

@pytest.mark.parametrize('args',[{'asset':'https://evil','project_name':'x'},{'asset':'spring','project_name':'../x'},{'asset':'spring','project_name':'x','script':'import os'}])
def test_protocol_rejects_remote_code_paths_urls(args):
 with pytest.raises(ProtocolError):parse_task(envelope(args))

def test_protocol_accepts_fixed_donor():
 assert parse_task(envelope({'asset':'spring','project_name':'donor1'})).arguments['asset']=='spring'

def test_missing_blender_is_blocked(monkeypatch):
 monkeypatch.setattr(r,'find_blender_executable',lambda:None)
 assert r.review_blender_source('spring','test')['status']=='blocked'

def test_pinned_source_hash_and_disabled_scripts(monkeypatch,tmp_path):
 exe=tmp_path/'blender';exe.write_bytes(b'not executable')
 source=tmp_path/'.local_agent/cache/spring-rig-source-v1/spring/spring/spring.blend'
 source.parent.mkdir(parents=True);source.write_bytes(b'original')
 monkeypatch.setenv('LOCAL_AGENT_WORKSPACE',str(tmp_path))
 monkeypatch.setattr(r,'find_blender_executable',lambda:exe)
 monkeypatch.setattr(r,'SPRING_TRANSFER_BLEND_SHA256',r._spring_sha256(source))
 def run(cmd,**kwargs):
  assert '--disable-autoexec' in cmd and '--offline-mode' in cmd and not kwargs['shell']
  assert cmd[-2]==str(source)
  Path(cmd[-1]).write_text(json.dumps({'mesh_count':1,'vertex_count':4,'meshes':[],'rigs':[],'images':[],'embedded_texts':[],'autoexec_enabled':False}))
  return SimpleNamespace(returncode=0,stderr='')
 monkeypatch.setattr(r.subprocess,'run',run)
 result=r.review_blender_source('spring','inspection1')
 assert result['status']=='completed' and result['identity_verified'] is False
 assert source.read_bytes()==b'original'
 assert r.review_blender_source('spring','inspection1')['reason']=='source_review_output_exists'


def test_hash_mismatch_never_opens_blender(monkeypatch,tmp_path):
 exe=tmp_path/'blender';exe.write_bytes(b'not executable')
 source=tmp_path/'.local_agent/cache/spring-rig-source-v1/spring/spring/spring.blend'
 source.parent.mkdir(parents=True);source.write_bytes(b'changed')
 monkeypatch.setenv('LOCAL_AGENT_WORKSPACE',str(tmp_path));monkeypatch.setattr(r,'find_blender_executable',lambda:exe)
 monkeypatch.setattr(r.subprocess,'run',lambda *a,**k:pytest.fail('must not launch'))
 assert r.review_blender_source('spring','inspection')['reason']=='source_digest_mismatch'
