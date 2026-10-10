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
    assert compiled["timeline"]["fps"] == 24
    assert compiled["timeline"]["clips"][0]["start_frame"] == 1
    assert compiled["timeline"]["clips"][0]["end_frame"] == 240
    assert compiled["timeline"]["readiness"] == "planning_only"
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
    assert data["timeline"]["scene_count"] == 1
    assert data["timeline"]["total_frames"] == 240
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
