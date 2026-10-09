from __future__ import annotations
import json
from pathlib import Path
import pytest
from local_agent.story_plan import StoryPlanError, save_story_plan, validate_story_plan

def sample_plan():
    return {"schema_version":1,"project_name":"mia_snail","title":"Мия и потерявшаяся улитка","logline":"Мия помогает улитке вернуться домой до заката.","target_duration_seconds":30,"language":"ru","character_bible":{"heroine":"Мия, девочка четырёх лет; постоянная внешность"},"scenes":[
    {"scene_id":"scene_001","title":"На лесной тропинке","duration_seconds":10,"location":"Солнечная лесная тропинка","action":"Мия замечает маленькую улитку возле листа.","camera":"Средний план, затем крупный план улитки","dialogue":[{"speaker":"Мия","text":"Ты потерялась?"}],"assets":["Mia_reference_model","snail","forest_path"],"sound":"Птицы, тихий ветер"},
    {"scene_id":"scene_002","title":"Дом под листом","duration_seconds":12,"location":"У большого папоротника","action":"Мия помогает улитке найти знакомый лист.","camera":"Низкий ракурс на уровне улитки","dialogue":[],"assets":["Mia_reference_model","snail","fern"]}],"continuity_notes":"Сохранять утверждённую внешность Мии."}
def test_validates_and_normalizes_story_plan():
    result=validate_story_plan(sample_plan()); assert result["estimated_scene_duration_seconds"]==22; assert result["scenes"][0]["dialogue"][0]["speaker"]=="Мия"
@pytest.mark.parametrize("mutator",[lambda p:p.update(project_name="../outside"),lambda p:p.update(schema_version=99),lambda p:p.update(scenes=[]),lambda p:p["scenes"][0].update(scene_id="../escape"),lambda p:p["scenes"][0].update(duration_seconds=True),lambda p:p["scenes"][0].update(script="import os")])
def test_rejects_unsafe_or_invalid_plans(mutator):
    plan=sample_plan(); mutator(plan)
    with pytest.raises(StoryPlanError): validate_story_plan(plan)
def test_saves_plan_inside_workspace_without_overwriting(tmp_path:Path):
    result=save_story_plan(tmp_path,sample_plan()); target=tmp_path/"mia_snail"/"story_plan.json"
    assert result["status"]=="completed" and target.is_file()
    assert json.loads(target.read_text(encoding="utf-8"))["title"]=="Мия и потерявшаяся улитка"
    with pytest.raises(StoryPlanError,match="refusing to overwrite"): save_story_plan(tmp_path,sample_plan())
def test_rejects_project_symlink_escape(tmp_path:Path):
    outside=tmp_path.parent/(tmp_path.name+"_outside"); outside.mkdir()
    try: (tmp_path/"mia_snail").symlink_to(outside,target_is_directory=True)
    except (OSError,NotImplementedError): pytest.skip("Symlink creation is unavailable on this platform")
    with pytest.raises(StoryPlanError,match="symlink"): save_story_plan(tmp_path,sample_plan())
