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

@pytest.mark.parametrize('args',[{'project_name':'../x'},{'project_name':'safe','script':'evil'},{}])
def test_source_adaptation_rejects_unsafe_inputs(args):
 value=json.loads(envelope(args));value['operation']='blender_mia_source_adapt'
 with pytest.raises(ProtocolError):parse_task(json.dumps(value))

def test_source_adaptation_requires_fixed_inputs(monkeypatch):
 monkeypatch.setattr(r,'find_blender_executable',lambda:None)
 assert r.adapt_spring_source_to_mia('pilot')['status']=='blocked'
 assert r.adapt_spring_source_to_mia('../outside')['status']=='rejected'


def test_source_adapt_script_parses_and_preserves_saved_geometry():
 import ast
 ast.parse(r.SOURCE_ADAPT_SCRIPT)
 assert 'saved_geometry_reopened_verified' in r.SOURCE_ADAPT_SCRIPT
 assert 'face_tests' in r.SOURCE_ADAPT_SCRIPT
 assert 'Mia_APPROVED_REFERENCE' in r.SOURCE_ADAPT_SCRIPT
 assert 'bone_snap' in r.SOURCE_ADAPT_SCRIPT


def test_recover_source_output_reads_existing_evidence_without_execution(monkeypatch,tmp_path):
 monkeypatch.setenv('LOCAL_AGENT_WORKSPACE',str(tmp_path))
 out=tmp_path/'SOURCE_ADAPTATIONS/pilot';out.mkdir(parents=True)
 (out/'mia_spring_source_adapted.blend').write_bytes(b'preserved output')
 tests={k:.03 for k in ('blink_max_delta','mouth_open_max_delta','head_pose_max_delta','arm_pose_max_delta','leg_pose_max_delta')}
 (out/'adaptation_report.json').write_text(json.dumps({'stage':'source_geometry_pilot_needs_review','saved_geometry_reopened_verified':True,'face_tests':tests,'source_mesh_changes':[]}))
 monkeypatch.setattr(r.subprocess,'run',lambda *a,**k:pytest.fail('must never rerun Blender'))
 result=r.recover_source_adaptation_result('pilot','original-job')
 assert result['recovered_existing_output'] is True and result['execution_repeated'] is False
 assert result['identity_verified'] is False
 assert result['status']=='completed'
 assert (out/'mia_spring_source_adapted.blend').read_bytes()==b'preserved output'

@pytest.mark.parametrize('args',[{'source_project':'../x','project_name':'y'},{'source_project':'x','project_name':'x'},{'source_project':'x','project_name':'y','script':'evil'}])
def test_neutral_source_copy_rejects_unsafe_or_overwrite_inputs(args):
 value=json.loads(envelope(args));value['operation']='blender_mia_source_neutral'
 with pytest.raises(ProtocolError):parse_task(json.dumps(value))


def test_neutral_copy_never_overwrites_source_identity():
 assert r.neutralize_saved_source_model('same','same')['status']=='rejected'


def test_detail_refinement_uses_last_saved_model_and_fixed_sources():
 value=json.loads(envelope({'source_project':'previous','project_name':'next'}));value['operation']='blender_mia_source_details'
 assert parse_task(json.dumps(value)).arguments['source_project']=='previous'
 assert r.refine_saved_source_details('same','same')['status']=='rejected'
 import ast
 ast.parse(r.SOURCE_DETAILS_SCRIPT)
