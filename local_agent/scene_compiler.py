"""Compile a validated story plan into a safe, inspectable storyboard manifest."""
from __future__ import annotations
from local_agent.path_names import path_identifier_pattern
import json, os, re
from pathlib import Path
from typing import Any
from local_agent.story_plan import StoryPlanError, validate_story_plan
from local_agent.asset_registry import read_asset_registry

_PROJECT_RE = path_identifier_pattern(48)
_ACTION_CAPABILITIES = {
    "idle": "character_rig_required",
    "look_at": "character_rig_required",
    "walk_to": "character_rig_required",
    "point_at": "character_rig_required",
    "wave": "character_rig_required",
    "pick_up": "character_rig_required",
    "put_down": "character_rig_required",
    "turn_toward": "character_rig_required",
    "camera_push_in": "camera_animation_adapter_required",
    "camera_pan": "camera_animation_adapter_required",
    "show_asset": "blender_asset_importer_required",
}

def _speaker_id(name: str) -> str:
    """Map common character names to stable IDs; hash unknown names deterministically."""
    import hashlib
    normalized = re.sub(r"\s+", " ", str(name).strip()).casefold()
    known = {
        "мия": "char.mia.master",
        "mia": "char.mia.master",
        "стёпа": "char.stepa.master",
        "степа": "char.stepa.master",
        "stepa": "char.stepa.master",
        "мама": "char.mama.master",
        "папа": "char.papa.master",
        "бабушка аня": "char.grandma_anya.master",
        "лев": "char.lev.master",
        "улитка спираль": "char.snail_spiral.master",
        "пип": "char.pip.master",
        "тишка": "char.tishka.master",
        "ква": "char.kva.master",
        "луна": "char.luna.master",
        "коля": "char.kolya.master",
        "бублик": "char.bublik.master",
        "рогач": "char.rogach.master",
    }
    if normalized in known:
        return known[normalized]
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]
    return "char.unknown_" + digest


def _estimated_dialogue_cues(
    scene_id: str, dialogue: list[dict[str, Any]], duration_seconds: int
) -> list[dict[str, Any]]:
    """Build rough open/closed events; these are not synchronized to recorded audio."""
    if not dialogue:
        return []
    fps = 30
    frame_end = max(1, int(duration_seconds * fps))
    valid_lines = [
        line for line in dialogue
        if isinstance(line.get("speaker", ""), str)
        and isinstance(line.get("text", ""), str)
        and line.get("text", "").strip()
    ]
    if not valid_lines:
        return []
    # Longer lines receive a larger estimated speaking window. This is only a
    # rough storyboard allocation; recorded voice timing must replace it later.
    weights = [
        max(1, len(re.findall(r"\w+", line["text"])))
        + min(3, sum(line["text"].count(mark) for mark in ".,!?;:"))
        for line in valid_lines
    ]
    total_weight = sum(weights)
    cues = []
    elapsed_weight = 0
    distributable_frames = frame_end - len(valid_lines)
    for index, (line, weight) in enumerate(zip(valid_lines, weights)):
        speaker = line.get("speaker", "")
        text = line.get("text", "")
        start = 1 + index + (elapsed_weight * distributable_frames) // total_weight
        elapsed_weight += weight
        end = index + 1 + (elapsed_weight * distributable_frames) // total_weight
        events = []
        frame = start
        state = "open"
        while frame <= end and len(events) < 250:
            events.append({"frame": frame, "mouth_state": state})
            state = "closed" if state == "open" else "open"
            frame += 4
        if not events:
            events = [{"frame": start, "mouth_state": "open"}]
        # End every estimated speaking window with a closed mouth so a line
        # cannot leave the character visibly speaking during the next silence.
        if events[-1]["mouth_state"] == "open":
            if events[-1]["frame"] < end:
                events.append({"frame": end, "mouth_state": "closed"})
            else:
                if len(events) > 1:
                    events.pop()  # The preceding event already closes the mouth.
                else:
                    events[-1]["mouth_state"] = "closed"
        cues.append({
            "speaker_id": _speaker_id(speaker),
            "line_id": f"{scene_id}_L{index + 1:03d}",
            "text": text.strip(),
            "timing_status": "estimated_until_voiceover",
            "events": events,
        })
    return cues

class StoryCompileError(ValueError):
    """A story plan cannot be safely compiled or stored."""

def compile_story_plan(data: Any) -> dict[str, Any]:
    """Convert validated story data to a non-executable storyboard manifest."""
    plan = validate_story_plan(data)
    compiled_scenes = []
    requirements = set()
    for scene in plan["scenes"]:
        steps = []
        for step in scene["action_steps"]:
            capability = _ACTION_CAPABILITIES[step["action"]]
            requirements.add(capability)
            steps.append({
                "action": step["action"],
                "actor": step["actor"],
                "target": step["target"],
                "duration_seconds": step["duration_seconds"],
                "notes": step["notes"],
                "execution_status": "not_executable_yet",
                "requires": capability,
            })
        assets = [{"name": name, "resolution_status": "unresolved_asset_reference"} for name in scene["assets"]]
        if assets:
            requirements.add("asset_registry_required")
        compiled_scenes.append({
            "scene_id": scene["scene_id"],
            "title": scene["title"],
            "duration_seconds": scene["duration_seconds"],
            "location_brief": scene["location"],
            "action_brief": scene["action"],
            "camera_brief": scene["camera"],
            "dialogue": scene["dialogue"],
            "dialogue_cues": _estimated_dialogue_cues(scene["scene_id"], scene["dialogue"], scene["duration_seconds"]),
            "sound_brief": scene["sound"],
            "transition": scene["transition"],
            "visual_prompt": scene["visual_prompt"],
            "assets": assets,
            "action_steps": steps,
            "execution_status": "planning_only",
        })
    return {
        "schema_version": 1,
        "compiler": "local_agent.scene_compiler",
        "project_name": plan["project_name"],
        "title": plan["title"],
        "logline": plan["logline"],
        "target_duration_seconds": plan["target_duration_seconds"],
        "estimated_scene_duration_seconds": plan["estimated_scene_duration_seconds"],
        "scene_count": len(compiled_scenes),
        "readiness": "planning_only",
        "requirements_not_implemented": sorted(requirements),
        "scenes": compiled_scenes,
        "safety_note": "This file is inert JSON data. It does not run Blender or execute natural-language instructions.",
    }

def compile_project_story(workspace: str | Path, project_name: str) -> dict[str, Any]:
    """Compile workspace/project/story_plan.json without overwriting previous output."""
    if not isinstance(project_name, str) or not _PROJECT_RE.fullmatch(project_name):
        raise StoryCompileError("Invalid project name.")
    root = Path(workspace).expanduser().resolve()
    project = root / project_name
    if project.is_symlink() or getattr(project, "is_junction", lambda: False)():
        raise StoryCompileError("Project directory must not be a symlink or junction.")
    project = project.resolve()
    if not project.is_relative_to(root) or not project.is_dir():
        raise StoryCompileError("Project directory is missing or outside the configured workspace.")
    source = project / "story_plan.json"
    if source.is_symlink() or not source.is_file():
        raise StoryCompileError("A regular story_plan.json file is required.")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
        compiled = compile_story_plan(raw)
    except (OSError, json.JSONDecodeError, StoryPlanError) as exc:
        raise StoryCompileError(f"Story plan could not be validated: {type(exc).__name__}") from exc
    if compiled["project_name"] != project_name:
        raise StoryCompileError("Story plan project_name does not match the requested project.")
    registry = read_asset_registry(project, project_name)
    unresolved = False
    if registry:
        compiled["requirements_not_implemented"] = [
            item for item in compiled["requirements_not_implemented"] if item != "asset_registry_required"
        ]
    for scene in compiled["scenes"]:
        for asset in scene["assets"]:
            match = registry.get(asset["name"])
            if match:
                asset["resolution_status"] = "resolved_local_file"
                asset["path"] = match["path"]
                if "blender_asset_importer_required" not in compiled["requirements_not_implemented"]:
                    compiled["requirements_not_implemented"].append("blender_asset_importer_required")
            else:
                unresolved = True
        for step in scene["action_steps"]:
            if step["action"] == "show_asset":
                match = registry.get(step["target"])
                if match:
                    step["target_resolution"] = {"status": "resolved_local_file", "path": match["path"]}
                    if "blender_asset_importer_required" not in compiled["requirements_not_implemented"]:
                        compiled["requirements_not_implemented"].append("blender_asset_importer_required")
                else:
                    step["target_resolution"] = {"status": "unresolved_asset_reference"}
                    unresolved = True
    if unresolved and "asset_registry_required" not in compiled["requirements_not_implemented"]:
        compiled["requirements_not_implemented"].append("asset_registry_required")
    compiled["requirements_not_implemented"] = sorted(set(compiled["requirements_not_implemented"]))
    destination = project / "storyboard_compile.json"
    if destination.is_symlink():
        raise StoryCompileError("Compiled output must not be a symlink.")
    if destination.exists():
        raise StoryCompileError("storyboard_compile.json already exists; refusing to overwrite it.")
    temp = project / ".storyboard_compile.json.tmp"
    owns_temp = False
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as stream:
            owns_temp = True
            json.dump(compiled, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        try:
            os.link(temp, destination)
        except FileExistsError as exc:
            raise StoryCompileError("storyboard_compile.json already exists; refusing to overwrite it.") from exc
        temp.unlink()
    finally:
        try:
            if owns_temp: temp.unlink(missing_ok=True)
        except OSError:
            pass
    return {
        "status": "completed",
        "project_name": project_name,
        "scene_count": compiled["scene_count"],
        "readiness": compiled["readiness"],
        "requirements_not_implemented": compiled["requirements_not_implemented"],
        "compiled_path": str(destination),
        "blender_launched": False,
        "render_created": False,
    }
