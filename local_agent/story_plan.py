"""Validated, data-only story plans authored by the remote creative director."""
from __future__ import annotations
import json, os, re
from pathlib import Path
from typing import Any
_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
_SCENE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
MAX_SCENES, MAX_PLAN_BYTES, MAX_TEXT = 80, 48_000, 4_000
class StoryPlanError(ValueError):
    """A story plan is malformed or unsafe to store."""
def _text(value: Any, label: str, *, limit: int = MAX_TEXT, required: bool = True) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit:
        qualifier = "non-empty string" if required else "string"
        raise StoryPlanError(f"{label} must be a {qualifier} of at most {limit} characters.")
    return value.strip()
def validate_story_plan(data: Any) -> dict[str, Any]:
    """Validate story content as inert JSON data; never interpret it as executable code."""
    if not isinstance(data, dict): raise StoryPlanError("Story plan must be a JSON object.")
    allowed = {"schema_version","project_name","title","logline","target_duration_seconds","language","character_bible","scenes","continuity_notes"}
    if set(data)-allowed: raise StoryPlanError("Story plan contains unsupported top-level fields.")
    if isinstance(data.get("schema_version"), bool) or not isinstance(data.get("schema_version"), int) or data.get("schema_version") != 1: raise StoryPlanError("Unsupported story plan schema_version.")
    project_name=data.get("project_name")
    if not isinstance(project_name,str) or not _PROJECT_RE.fullmatch(project_name): raise StoryPlanError("project_name must use 1-48 letters, digits, underscores, or hyphens.")
    title=_text(data.get("title"),"title",limit=180); logline=_text(data.get("logline"),"logline",limit=1200)
    duration=data.get("target_duration_seconds")
    if isinstance(duration,bool) or not isinstance(duration,int) or not 5<=duration<=1800: raise StoryPlanError("target_duration_seconds must be an integer from 5 to 1800.")
    language=_text(data.get("language","ru"),"language",limit=20)
    bible=data.get("character_bible",{})
    if not isinstance(bible,dict) or len(json.dumps(bible,ensure_ascii=False))>4000: raise StoryPlanError("character_bible must be an object no larger than 4000 characters.")
    notes=_text(data.get("continuity_notes",""),"continuity_notes",limit=2000,required=False)
    raw_scenes=data.get("scenes")
    if not isinstance(raw_scenes,list) or not raw_scenes or len(raw_scenes)>MAX_SCENES: raise StoryPlanError(f"scenes must contain 1-{MAX_SCENES} scenes.")
    scenes=[]; seen=set(); total=0
    allowed_scene={"scene_id","title","duration_seconds","location","action","camera","dialogue","assets","sound","transition","visual_prompt","action_steps"}
    for index,scene in enumerate(raw_scenes,1):
        if not isinstance(scene,dict) or set(scene)-allowed_scene: raise StoryPlanError(f"Scene {index} contains unsupported fields.")
        scene_id=scene.get("scene_id",f"scene_{index:03d}")
        if not isinstance(scene_id,str) or not _SCENE_RE.fullmatch(scene_id) or scene_id in seen: raise StoryPlanError(f"Scene {index} has an invalid or duplicate scene_id.")
        seen.add(scene_id); seconds=scene.get("duration_seconds",5)
        if isinstance(seconds,bool) or not isinstance(seconds,int) or not 1<=seconds<=120: raise StoryPlanError(f"Scene {index} duration_seconds must be an integer from 1 to 120.")
        total+=seconds; dialogue=scene.get("dialogue",[])
        if not isinstance(dialogue,list) or len(dialogue)>30: raise StoryPlanError(f"Scene {index} dialogue must be a list of at most 30 lines.")
        clean_dialogue=[]
        for line_no,line in enumerate(dialogue,1):
            if not isinstance(line,dict) or set(line)-{"speaker","text","delivery"}: raise StoryPlanError(f"Scene {index} dialogue line {line_no} is malformed.")
            clean_dialogue.append({"speaker":_text(line.get("speaker"),f"Scene {index} speaker",limit=80),"text":_text(line.get("text"),f"Scene {index} dialogue text",limit=700),"delivery":_text(line.get("delivery","natural"),f"Scene {index} delivery",limit=100)})
        steps=scene.get("action_steps",[])
        allowed_actions={"idle","look_at","walk_to","point_at","wave","pick_up","put_down","turn_toward","camera_push_in","camera_pan","show_asset"}
        if not isinstance(steps,list) or len(steps)>40: raise StoryPlanError(f"Scene {index} action_steps must be a list of at most 40 steps.")
        clean_steps=[]
        for step_no,step in enumerate(steps,1):
            if not isinstance(step,dict) or set(step)-{"action","actor","target","duration_seconds","notes"}: raise StoryPlanError(f"Scene {index} action step {step_no} is malformed.")
            action=step.get("action")
            if not isinstance(action,str) or action not in allowed_actions: raise StoryPlanError(f"Scene {index} action step {step_no} uses an unsupported action.")
            step_duration=step.get("duration_seconds",2)
            if isinstance(step_duration,bool) or not isinstance(step_duration,(int,float)) or not 0.1<=step_duration<=60: raise StoryPlanError(f"Scene {index} action step {step_no} duration must be between 0.1 and 60 seconds.")
            clean_steps.append({"action":action,"actor":_text(step.get("actor","Mia"),f"Scene {index} action actor",limit=80),
                "target":_text(step.get("target",""),f"Scene {index} action target",limit=120,required=False),
                "duration_seconds":float(step_duration),"notes":_text(step.get("notes",""),f"Scene {index} action notes",limit=500,required=False)})
        assets=scene.get("assets",[])
        if not isinstance(assets,list) or len(assets)>40: raise StoryPlanError(f"Scene {index} assets must be a list of at most 40 names.")
        clean_assets=[_text(x,f"Scene {index} asset",limit=120) for x in assets]
        scenes.append({"scene_id":scene_id,"title":_text(scene.get("title",f"Scene {index}"),f"Scene {index} title",limit=180),"duration_seconds":seconds,
          "location":_text(scene.get("location"),f"Scene {index} location",limit=600),"action":_text(scene.get("action"),f"Scene {index} action",limit=3000),
          "camera":_text(scene.get("camera","medium shot"),f"Scene {index} camera",limit=600),"dialogue":clean_dialogue,"action_steps":clean_steps,"assets":clean_assets,
          "sound":_text(scene.get("sound",""),f"Scene {index} sound",limit=600,required=False),"transition":_text(scene.get("transition","cut"),f"Scene {index} transition",limit=100),
          "visual_prompt":_text(scene.get("visual_prompt",""),f"Scene {index} visual_prompt",limit=2000,required=False)})
    if total>duration*2: raise StoryPlanError("Total scene duration is implausibly long compared with target_duration_seconds.")
    result={"schema_version":1,"project_name":project_name,"title":title,"logline":logline,"target_duration_seconds":duration,"estimated_scene_duration_seconds":total,"language":language,"character_bible":bible,"scenes":scenes,"continuity_notes":notes}
    if len(json.dumps(result,ensure_ascii=False).encode("utf-8"))>MAX_PLAN_BYTES: raise StoryPlanError("Validated story plan exceeds the 48 KB limit.")
    return result
def save_story_plan(workspace: str | Path, data: Any) -> dict[str, Any]:
    """Atomically store a validated plan under workspace/project/story_plan.json."""
    plan=validate_story_plan(data); root=Path(workspace).expanduser().resolve(); root.mkdir(parents=True,exist_ok=True)
    project=root/plan["project_name"]
    if project.is_symlink() or getattr(project,"is_junction",lambda:False)(): raise StoryPlanError("Project folder must not be a symlink or junction.")
    project.mkdir(parents=True,exist_ok=True); resolved=project.resolve()
    if not resolved.is_relative_to(root): raise StoryPlanError("Project folder resolves outside the configured workspace.")
    destination=resolved/"story_plan.json"
    if destination.is_symlink(): raise StoryPlanError("Story plan destination must not be a symlink.")
    if destination.exists(): raise StoryPlanError("story_plan.json already exists; refusing to overwrite it.")
    temp=resolved/".story_plan.json.tmp"
    try:
        with temp.open("x",encoding="utf-8",newline="\n") as stream:
            json.dump(plan,stream,ensure_ascii=False,indent=2); stream.write("\n")
        try:
            os.link(temp, destination)  # Atomic no-clobber creation on the same filesystem.
        except FileExistsError as exc:
            raise StoryPlanError("story_plan.json already exists; refusing to overwrite it.") from exc
        temp.unlink()
    finally:
        try: temp.unlink(missing_ok=True)
        except OSError: pass
    return {"status":"completed","project_name":plan["project_name"],"title":plan["title"],"scene_count":len(plan["scenes"]),"estimated_scene_duration_seconds":plan["estimated_scene_duration_seconds"],"plan_path":str(destination),"execution_started":False,"blender_launched":False}
