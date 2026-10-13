"""Safe Astra Mia v2: approved reference crops, multiple edits, only front to owner."""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from local_agent.blender_workflow import (
    _mia_v2_commands, _mia_v2_blender_script, _mia_v2_prepare_references,
    run_mia_astra_autoloop_100_v2, BlenderWorkflowError, _MIA_V2_SOURCE)
from local_agent.control_protocol import parse_task, ProtocolError


def envelope(args=None):
    return json.dumps({"protocol_version":1,"task_id":"mia-100-v2-test",
        "operation":"mia_astra_autoloop_100_v2","created_at":"2026-10-13T00:00:00+00:00",
        "expires_at":"2026-10-13T01:00:00+00:00",
        "requires_local_approval":True,"arguments":args or {}})


def test_no_remote_paths_or_arbitrary_code():
    assert parse_task(envelope()).operation=="mia_astra_autoloop_100_v2"
    for bad in ({"script":"evil"},{"url":"https://example.org"},{"iterations":100},
                {"model":"other"},{"path":"../../../somewhere"}):
        with pytest.raises(ProtocolError):
            parse_task(envelope(bad))


def test_many_safe_commands_and_no_code():
    raw=json.dumps({"verdict":"continue","score":24,"priority_summary":"face and hair",
         "commands":[
             {"target":"eyes","action":"adjust_geometry","delta":-.05,"reason":"smaller"},
             {"target":"side_fringe","action":"adjust_geometry","delta":.04,"reason":"move"},
             {"target":"hair_tone","action":"adjust_material","delta":.04,"reason":"lighten"},
         ]})
    result=_mia_v2_commands(raw)
    assert len(result["commands"])==3
    for bad in [
        {"verdict":"continue","score":22,"priority_summary":"unsafe","commands":[
             {"target":"eyes","action":"execute_code","delta":.01,"reason":"bad"}]},
        {"verdict":"continue","score":22,"priority_summary":"unsafe","commands":[
             {"target":"hair_tone","action":"adjust_geometry","delta":.01,"reason":"bad"}]},
        {"verdict":"continue","score":22,"priority_summary":"unsafe","commands":[
             {"target":"eyes","action":"adjust_geometry","delta":4,"reason":"bad"}]},
        {"verdict":"continue","score":22,"priority_summary":"unsafe","commands":[]},
        {"verdict":"continue","score":22,"priority_summary":"unsafe","commands":[
             {"target":"eyes","action":"adjust_geometry","delta":.01,"reason":"ok",
             "python":"malware"}]},
    ]:
        with pytest.raises(BlenderWorkflowError):
            _mia_v2_commands(json.dumps(bad))


def test_safe_blender_script_renders_only_three_diagnostic_stills():
    code=_mia_v2_blender_script()
    ast.parse(code)
    assert "for command in commands" in code
    assert '("front",(0,-8,2.3))' in code
    assert '("side",(8,0,2.3))' in code
    assert '("back",(0,8,2.3))' in code
    assert "bpy.ops.wm.save_as_mainfile" in code
    assert "bpy.ops.render.render(write_still=True)" in code
    assert "exec(" not in code
    assert "animation=True" not in code


def test_real_reference_derivatives_crop_black_margins_and_head(monkeypatch,tmp_path):
    from local_agent import blender_workflow as wf
    src=tmp_path/"approved.jpeg";src.write_bytes(b"\xff\xd8\xff"+b"fake reference")
    class Sha:
        def hexdigest(self):return wf._MIA_V2_REF_SHA
    monkeypatch.setattr(hashlib,"sha256",lambda *args:Sha())
    import shutil
    monkeypatch.setattr(shutil,"which",lambda name:"ffmpeg" if name=="ffmpeg" else None)
    import subprocess
    calls=[]
    def fake_run(cmd,**kwargs):
        Path(cmd[-1]).write_bytes(b"\x89PNG\r\n\x1a\n"+b"R"*1200)
        calls.append(" ".join(cmd))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess,"run",fake_run)
    results=_mia_v2_prepare_references(tmp_path,src,tmp_path/"approved_crop")
    assert len(results)==5
    assert all(p.exists() for p in results.values())
    assert "crop=" in calls[0] and "0.310" in calls[0]
    assert any("head_front" in x for x in calls)
    assert (tmp_path/"approved_crop"/"source_integrity.json").exists()


def test_hundred_mock_cycles_one_front_each_and_final_only(monkeypatch,tmp_path):
    from local_agent import blender_workflow as wf
    from local_agent import mailbox_policy,studio_server,octava_credentials
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    source=tmp_path/"MIA_REFERENCE_REVIEW"/_MIA_V2_SOURCE
    source.mkdir(parents=True)
    (source/"mia_reference_model.blend").write_bytes(b"BLENDER"+b"X"*1200)
    for name in ("front","side","back"):
        (source/(name+".png")).write_bytes(b"\x89PNG\r\n\x1a\n"+name.encode()*80)
    canonical=tmp_path/"episode1/assets/references/mia_turnaround_approved_20261012.jpeg"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"\xff\xd8\xff"+b"Y"*1200)
    original_sha=hashlib.sha256
    class FakeSha:
        def hexdigest(self):return wf._MIA_V2_REF_SHA
    monkeypatch.setattr(hashlib,"sha256",lambda *args:FakeSha())
    blender=tmp_path/"blender.exe";blender.write_text("stub")
    monkeypatch.setattr(wf,"find_blender_executable",lambda:blender)
    monkeypatch.setattr(wf,"_agent_cancel_requested",lambda *_:False)
    monkeypatch.setattr(wf,"_validate_png",lambda *args:(True,"ok",(600,900)))
    monkeypatch.setattr(wf,"_mia_v2_similarity",lambda before,after:(True,"ssim_0.9721"))
    def fake_refs(workspace,origin,out):
        out.mkdir()
        result={}
        for filename in ("mia_turnaround_clean.png","mia_head_front.png",
                         "mia_head_side.png","mia_head_back_hair.png","mia_front_full.png"):
            file=out/filename
            file.write_bytes(b"\x89PNG\r\n\x1a\n"+b"ref"*1000)
            result[filename]=file
        return result
    monkeypatch.setattr(wf,"_mia_v2_prepare_references",fake_refs)
    monkeypatch.setattr(mailbox_policy,"load_policy",lambda:{
        "enabled":True,"allow_octava":True,"allow_blender":True})
    monkeypatch.setattr(mailbox_policy,"telegram_notifications_enabled",lambda:True)
    monkeypatch.setattr(studio_server,"_telegram_credentials",lambda:("111:TEST_TOKEN","222"))
    monkeypatch.setattr(octava_credentials,"read_key",lambda:("KEY","vault"))
    vision=[]
    def fake_astra(key,refs,views,cycle,state,*,single_pass=False):
        assert single_pass is False
        assert len(refs)==5 and len(views)==3
        vision.append(cycle)
        return _mia_v2_commands(json.dumps({
            "verdict":"continue","score":30,"priority_summary":"face",
            "commands":[
                {"target":"eyes","action":"adjust_geometry","delta":-.01,"reason":"face"},
                {"target":"side_fringe","action":"adjust_geometry","delta":.01,"reason":"hair"},
                {"target":"hair_tone","action":"adjust_material","delta":.01,"reason":"tone"}]}))
    monkeypatch.setattr(wf,"_mia_v2_request",fake_astra)
    def fake_blender(args,*,cwd,timeout,task_id):
        config=json.loads(Path(args[-1]).read_text())
        assert len(config["commands"])==3
        assert timeout==960
        (cwd/"mia_reference_model.blend").write_bytes(b"BLENDER"+b"X"*1200)
        for view in ("front","side","back"):
            (cwd/(view+".png")).write_bytes(b"\x89PNG\r\n\x1a\n"+view.encode()*80)
        (cwd/"applied_commands.json").write_text(json.dumps(
            {"total_modified_elements":333,"commands":config["commands"]}))
        return SimpleNamespace(returncode=0),False,False,"",None
    monkeypatch.setattr(wf,"_run_cancellable_process",fake_blender)
    import requests
    photos=[]
    def fake_photo(url,**kw):
        assert url.endswith("/sendPhoto") and kw["data"]["chat_id"]=="222"
        assert kw["files"]["photo"][0]=="front.png"
        assert kw["files"]["photo"][1].read(8)==b"\x89PNG\r\n\x1a\n"
        photos.append(kw["data"]["caption"])
        return SimpleNamespace(status_code=200,
           headers={"Content-Type":"application/json"},json=lambda:{"ok":True})
    monkeypatch.setattr(requests,"post",fake_photo)
    result=wf.run_mia_astra_autoloop_100_v2(task_id="mia-100-v2-test")
    assert result["status"]=="completed"
    assert result["cycles_completed"]==100
    assert len(vision)==len(photos)==100
    assert "001/100" in photos[0] and "100/100" in photos[-1]
    run=tmp_path/"MIA_REFERENCE_REVIEW"/"MIA_AUTOLOOP_V2_mia-100-v2-test"
    assert len(list(run.glob("cycle_*/front.png")))==100
    assert len(list(run.glob("cycle_*/side.png")))==100
    assert len(list(run.glob("cycle_*/back.png")))==100
    assert len(list(run.glob("cycle_*/mia_reference_model.blend")))==100
    assert len(list(run.glob("cycle_*/telegram_delivery.json")))==100
    assert (source/"mia_reference_model.blend").is_file()


def test_fails_safe_before_network_without_explicit_local_permission(monkeypatch,tmp_path):
    from local_agent import mailbox_policy
    monkeypatch.setattr(mailbox_policy,"load_policy",lambda:{
       "enabled":True,"allow_octava":True,"allow_blender":False})
    assert run_mia_astra_autoloop_100_v2(task_id="no-blender")["status"]=="blocked"
