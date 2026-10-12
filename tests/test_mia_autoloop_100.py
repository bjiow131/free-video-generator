"""Autonomous 100-pass Mira/Mia image review: strict no-code and final-only behavior."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from local_agent import blender_workflow as wf
from local_agent.control_protocol import parse_task, ProtocolError


def _task(args):
    return json.dumps({"protocol_version":1,"task_id":"mia-loop-test",
        "operation":"mia_astra_autoloop_100",
        "created_at":"2026-10-13T00:00:00+00:00",
        "expires_at":"2026-10-13T01:00:00+00:00",
        "requires_local_approval":True,"arguments":args})


def test_remote_operation_has_no_code_or_arbitrary_paths():
    assert parse_task(_task({})).operation=="mia_astra_autoloop_100"
    for bad in ({"count":101},{"script":"exec()"},{"path":"../x"},{"model":"other"}):
        with pytest.raises(ProtocolError):
            parse_task(_task(bad))


def test_command_is_one_bounded_edit_and_never_python():
    assert wf._mia_autoloop_command('{"area":"eyes","delta":-.01,"reason":"too large","score":40}')["area"]=="eyes"
    for invalid in ('{"script":"import os"}',
                    '{"area":"eyes","delta":1,"reason":"no","score":20}',
                    '{"area":"eyes","delta":0.0,"reason":"no","score":20}',
                    '{"area":"eyes","delta":.01,"reason":"bad","score":20}',
                    '{"area":"eyes","delta":0.01,"reason":"x","score":20,"code":"print()"}',
                    '{"area":"invent_new_mia","delta":.01,"reason":"x","score":20}',
                    '{"area":"eyes","delta":true,"reason":"x","score":20}'):
        with pytest.raises(wf.BlenderWorkflowError):
            wf._mia_autoloop_command(invalid)


def test_fixed_blender_script_is_static_and_only_selected_meshes():
    src=wf._mia_autoloop_script()
    ast.parse(src)
    assert "bpy.ops.wm.save_as_mainfile(filepath=" in src
    assert "bpy.ops.render.render(write_still=True)" in src
    assert "mia_sculpted_head" in src
    assert "side_swept_fringe_" in src
    assert "exec(" not in src
    assert "animation=True" not in src
    assert "mp4" not in src


def test_complete_100_cycles_deliver_one_front_each_and_no_intermediate_mailbox(monkeypatch,tmp_path):
    ws=tmp_path
    initial=ws/"MIA_REFERENCE_REVIEW"/wf._MIA_AUTOMODEL_SOURCE
    initial.mkdir(parents=True)
    (initial/"mia_reference_model.blend").write_bytes(b"BLENDER"+b"0"*1200)
    (initial/"front.png").write_bytes(b"\x89PNG\r\n\x1a\n"+b"F"*88)
    approved=ws/"episode1"/"assets"/"references"/"mia_turnaround_approved_20261012.jpeg"
    approved.parent.mkdir(parents=True)
    approved.write_bytes(b"\xff\xd8\xff"+b"M"*(111601-3))
    import hashlib
    class Digest:
        def hexdigest(self):return wf._MIA_AUTOMODEL_REF_SHA
    monkeypatch.setattr(hashlib,"sha256",lambda *args:Digest())
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(ws))
    exe=ws/"blender.exe";exe.write_text("fake")
    monkeypatch.setattr(wf,"find_blender_executable",lambda:exe)
    monkeypatch.setattr(wf,"_agent_cancel_requested",lambda *_:False)
    monkeypatch.setattr(wf,"_validate_png",lambda *args:(True,"ok",(600,900)))
    import local_agent.mailbox_policy as policy
    monkeypatch.setattr(policy,"load_policy",
        lambda:{"enabled":True,"allow_blender":True,"allow_octava":True})
    monkeypatch.setattr(policy,"telegram_notifications_enabled",lambda:True)
    import local_agent.studio_server as studio
    monkeypatch.setattr(studio,"_telegram_credentials",lambda:("12345:TOKEN","98765"))
    import local_agent.octava_credentials as creds
    monkeypatch.setattr(creds,"read_key",lambda:("SAFE_DUMMY_KEY","windows_store"))

    model_calls=[]
    def fake_astra(key,reference,front,cycle,history):
        assert key=="SAFE_DUMMY_KEY" and len(front)>8
        model_calls.append(cycle)
        return {"area":("eyes" if cycle%2 else "side_fringe"),
                "delta":(-.005 if cycle%2 else .005),
                "reason":"small 3d geometry improvement","score":min(99,cycle*.8)}
    monkeypatch.setattr(wf,"_mia_autoloop_astra",fake_astra)
    def fake_blender(command,*,cwd,timeout,task_id):
        cfg=json.loads(Path(command[-1]).read_text())
        assert cfg["out"]==str(cwd) and timeout==600
        (cwd/"mia_reference_model.blend").write_bytes(b"BLENDER"+b"1"*1200)
        (cwd/"front.png").write_bytes(b"\x89PNG\r\n\x1a\n"+b"R"*88)
        (cwd/"model_result.json").write_text(json.dumps(
            {"changed_vertices_or_materials":50,"cycle":cfg["cycle"]}))
        return SimpleNamespace(returncode=0),False,False,"",None
    monkeypatch.setattr(wf,"_run_cancellable_process",fake_blender)
    import requests
    telegram=[]
    def fake_post(url,**kwargs):
        assert url.endswith("/sendPhoto")
        assert kwargs["data"]["chat_id"]=="98765"
        assert kwargs["files"]["photo"][0]=="front.png"
        assert kwargs["files"]["photo"][1].read(8)==b"\x89PNG\r\n\x1a\n"
        telegram.append(kwargs["data"]["caption"])
        return SimpleNamespace(status_code=200,headers={"Content-Type":"application/json"},
                               json=lambda:{"ok":True})
    monkeypatch.setattr(requests,"post",fake_post)
    finished=wf.run_mia_astra_autoloop_100(task_id="mia-loop-test")
    assert finished["status"]=="completed"
    assert finished["completed_cycles"]==100
    assert finished["telegram_front_photos_sent"]==100
    assert len(model_calls)==len(telegram)==100
    assert telegram[0].count("001/100")==1 and "100/100" in telegram[-1]
    assert "front" in telegram[0].lower()
    root=ws/"MIA_REFERENCE_REVIEW"/"MIA_AUTOLOOP_100_mia-loop-test"
    assert len(list(root.glob("cycle_*/front.png")))==100
    assert len(list(root.glob("cycle_*/mia_reference_model.blend")))==100
    assert (initial/"mia_reference_model.blend").exists()
    assert json.loads((root/"checkpoint.json").read_text())["completed_cycles"]==100


def test_fails_closed_without_credentials_or_canonical_model(monkeypatch,tmp_path):
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    from local_agent import mailbox_policy
    monkeypatch.setattr(mailbox_policy,"load_policy",
                        lambda:{"enabled":True,"allow_blender":False,"allow_octava":True})
    assert wf.run_mia_astra_autoloop_100(task_id="mia-locked")["status"]=="blocked"
