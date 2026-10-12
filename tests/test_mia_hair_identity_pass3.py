"""Hair reconstruction must be an isolated versioned 3D change, not a new cartoon."""
import ast
import json
import pytest
from local_agent.control_protocol import ProtocolError, parse_task
from local_agent.blender_workflow import (
    create_mia_hair_identity_pass_three, _mia_hair_identity_pass_three_script,
)

def task(args):
    return json.dumps({"protocol_version":1,"task_id":"mia-hair-test-01",
        "operation":"mia_hair_identity_pass_three",
        "created_at":"2026-10-13T01:00:00+00:00",
        "expires_at":"2026-10-13T01:25:00+00:00",
        "requires_local_approval":True,"arguments":args})

def test_fixed_operation_forbids_remote_code():
    assert parse_task(task({})).operation == "mia_hair_identity_pass_three"
    for args in ({"prompt":"another girl"},{"python":"import os"},{"file":"../evil"},{"duration":8}):
        with pytest.raises(ProtocolError):
            parse_task(task(args))

def test_real_hair_geometry_is_changed_but_not_face():
    code=_mia_hair_identity_pass_three_script()
    ast.parse(code)
    for fragment in ("side_swept_fringe_","gathered_back_lock_",
                     "natural_crown_fiber_","bun_fine_fiber",
                     'bpy.ops.wm.save_as_mainfile(filepath=blend)',
                     "bpy.ops.render.render(write_still=True)"):
        assert fragment in code
    assert 'mia_sculpted_head' not in code
    assert 'eye_sclera' not in code
    assert "mp4" not in code
    assert "scene.frame_set(" not in code
    assert "bpy.ops.render.render(animation=True)" not in code

def test_parent_files_not_overwritten_if_missing(monkeypatch,tmp_path):
    from local_agent import blender_workflow as wf
    blender=tmp_path/"blender.exe"
    blender.write_text("stub")
    monkeypatch.setattr(wf,"find_blender_executable",lambda:blender)
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    r=create_mia_hair_identity_pass_three(task_id="review-one")
    assert r["status"]=="blocked"
    assert not (tmp_path/"MIA_REFERENCE_REVIEW"/"review-one").exists()
