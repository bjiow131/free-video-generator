"""Fixed, reversible static Mia correction pass after Astra vision review."""
import ast
import json
from local_agent.control_protocol import parse_task, ProtocolError
from local_agent.blender_workflow import create_mia_astra_pass_one, _mia_astra_pass1_script
import pytest

def task(args):
    return json.dumps({"protocol_version":1,"task_id":"mia-test-pass1",
        "operation":"mia_astra_pass_one",
        "created_at":"2026-10-13T00:00:00+00:00",
        "expires_at":"2026-10-13T00:20:00+00:00",
        "requires_local_approval":True,"arguments":args})

def test_pass_one_requires_no_external_code_paths_parameters():
    assert parse_task(task({})).operation=="mia_astra_pass_one"
    for args in ({"filepath":"x"},{"script":"evil"},{"prompt":"create a different girl"},{"duration_seconds":5}):
        with pytest.raises(ProtocolError):
            parse_task(task(args))

def test_bundled_blender_script_is_syntactically_valid_static_and_versions():
    src=_mia_astra_pass1_script()
    ast.parse(src)
    assert 'bpy.ops.wm.save_as_mainfile(filepath=blend)' in src
    assert 'output' not in src.split('config = json.load')[0]
    assert 'animation=True' not in src
    assert 'source_mia_reference' not in src
    assert 'for name, pos in views' in src
    assert 'identity_status' in src

def test_missing_local_reference_stops_before_blender(monkeypatch,tmp_path):
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    from local_agent import blender_workflow as workflow
    blender=tmp_path/"blender"
    blender.write_bytes(b"X")
    monkeypatch.setattr(workflow,"find_blender_executable",lambda:blender)
    result=create_mia_astra_pass_one(task_id="test-fixedpass1")
    assert result["status"]=="blocked"
    assert not (tmp_path/"MIA_REFERENCE_REVIEW"/"test-fixedpass1").exists()

def test_invalid_name_never_creates_project(monkeypatch,tmp_path):
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    result=create_mia_astra_pass_one(task_id="../unsafe")
    assert result["status"]=="blocked"
