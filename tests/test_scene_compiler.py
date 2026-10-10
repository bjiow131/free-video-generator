from __future__ import annotations
import json
from pathlib import Path
import pytest
from local_agent.scene_compiler import StoryCompileError, compile_project_story, compile_story_plan
from local_agent.story_plan import save_story_plan

def sample_plan():
    return {"schema_version":1,"project_name":"mia_snail","title":"Мия и улитка","logline":"Мия помогает улитке.","target_duration_seconds":30,"language":"ru","character_bible":{"heroine":"Сохранять внешний вид Мии"},"scenes":[
      {"scene_id":"scene_001","title":"Встреча","duration_seconds":10,"location":"Лесная тропинка","action":"Мия замечает улитку","camera":"Крупный план","dialogue":[{"speaker":"Мия","text":"Привет!"}],"action_steps":[{"action":"look_at","actor":"Mia","target":"snail","duration_seconds":1.5},{"action":"camera_push_in","actor":"camera","target":"snail","duration_seconds":2}],"assets":["Mia_reference_model","snail"]}]}

def test_compiler_marks_missing_capabilities_instead_of_claiming_execution():
    compiled=compile_story_plan(sample_plan())
    assert compiled["readiness"]=="planning_only"
    assert compiled["scene_count"]==1
    assert compiled["scenes"][0]["action_steps"][0]["execution_status"]=="not_executable_yet"
    assert "character_rig_required" in compiled["requirements_not_implemented"]
    assert "asset_registry_required" in compiled["requirements_not_implemented"]

def test_compiles_saved_story_plan_without_overwrite(tmp_path:Path):
    save_story_plan(tmp_path,sample_plan())
    result=compile_project_story(tmp_path,"mia_snail")
    output=tmp_path/"mia_snail"/"storyboard_compile.json"
    assert result["status"]=="completed" and output.is_file()
    data=json.loads(output.read_text(encoding="utf-8"))
    assert data["scenes"][0]["action_steps"][1]["action"]=="camera_push_in"
    with pytest.raises(StoryCompileError,match="refusing to overwrite"):
        compile_project_story(tmp_path,"mia_snail")

def test_rejects_missing_plan_and_unsafe_project(tmp_path:Path):
    with pytest.raises(StoryCompileError):
        compile_project_story(tmp_path,"../outside")
    (tmp_path/"mia_snail").mkdir()
    with pytest.raises(StoryCompileError,match="story_plan.json"):
        compile_project_story(tmp_path,"mia_snail")

def test_rejects_mismatched_project_name(tmp_path:Path):
    plan=sample_plan()
    plan["project_name"]="other_project"
    project=tmp_path/"mia_snail"
    project.mkdir()
    (project/"story_plan.json").write_text(json.dumps(plan),encoding="utf-8")
    with pytest.raises(StoryCompileError,match="does not match"):
        compile_project_story(tmp_path,"mia_snail")


def test_compiler_resolves_assets_from_local_registry(tmp_path: Path):
    from local_agent.asset_registry import scan_project_assets
    save_story_plan(tmp_path, sample_plan())
    assets = tmp_path / "mia_snail" / "assets"
    assets.mkdir(parents=True)
    (assets / "Mia_reference_model.blend").write_bytes(b"placeholder")
    (assets / "snail.png").write_bytes(b"placeholder")
    scan_project_assets(tmp_path, "mia_snail")
    result = compile_project_story(tmp_path, "mia_snail")
    compiled = json.loads(Path(result["compiled_path"]).read_text(encoding="utf-8"))
    resolved = {asset["name"]: asset for asset in compiled["scenes"][0]["assets"]}
    assert resolved["snail"]["resolution_status"] == "resolved_local_file"
    assert resolved["snail"]["path"] == "assets/snail.png"
    assert "blender_asset_importer_required" in compiled["requirements_not_implemented"]
    assert "asset_registry_required" not in compiled["requirements_not_implemented"]


def test_compiler_emits_estimated_dialogue_cues_with_stable_ids():
    compiled = compile_story_plan(sample_plan())
    scene = compiled["scenes"][0]
    cues = scene["dialogue_cues"]
    assert len(cues) == 1
    cue = cues[0]
    assert cue["speaker_id"] == "char.mia.master"
    assert cue["line_id"] == "scene_001_L001"
    assert cue["timing_status"] == "estimated_until_voiceover"
    assert cue["events"][0]["mouth_state"] == "open"
    assert all(1 <= event["frame"] <= 300 for event in cue["events"])
    assert all(
        cue["events"][index]["frame"] < cue["events"][index + 1]["frame"]
        for index in range(len(cue["events"]) - 1)
    )
    assert cue["events"][-1]["mouth_state"] == "closed"


def test_compiler_closes_each_speaker_window_before_the_next_line():
    plan = sample_plan()
    plan["scenes"][0]["duration_seconds"] = 20
    plan["scenes"][0]["dialogue"] = [
        {"speaker": "Мия", "text": "Да."},
        {"speaker": "Стёпа", "text": "Давай посмотрим внимательно на эту маленькую улитку!"},
    ]
    cues = compile_story_plan(plan)["scenes"][0]["dialogue_cues"]
    assert len(cues) == 2
    assert all(cue["events"][-1]["mouth_state"] == "closed" for cue in cues)
    assert cues[0]["events"][-1]["frame"] <= cues[1]["events"][0]["frame"]


def test_compiler_leaves_silent_scene_without_dialogue_cues():
    plan = sample_plan()
    plan["scenes"][0]["dialogue"] = []
    compiled = compile_story_plan(plan)
    assert compiled["scenes"][0]["dialogue_cues"] == []


def test_estimated_dialogue_window_scales_with_line_length():
    plan = sample_plan()
    plan["scenes"][0]["duration_seconds"] = 20
    plan["scenes"][0]["dialogue"] = [
        {"speaker": "Мия", "text": "Да."},
        {"speaker": "Стёпа", "text": "Давай посмотрим внимательно на эту маленькую улитку!"},
    ]
    cues = compile_story_plan(plan)["scenes"][0]["dialogue_cues"]
    first_span = cues[0]["events"][-1]["frame"] - cues[0]["events"][0]["frame"]
    second_span = cues[1]["events"][-1]["frame"] - cues[1]["events"][0]["frame"]
    assert cues[0]["speaker_id"] == "char.mia.master"
    assert cues[1]["speaker_id"] == "char.stepa.master"
    assert second_span > first_span
    assert all(cue["timing_status"] == "estimated_until_voiceover" for cue in cues)
