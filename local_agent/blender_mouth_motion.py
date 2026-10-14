"""Apply coarse dialogue mouth cues to discovered Blender mouth shape keys, saving a copy."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")


def _blender_script() -> str:
    return r'''
import bpy, json, re, sys
args=sys.argv[sys.argv.index("--")+1:]
with open(args[0],encoding="utf-8") as stream:
    cfg=json.load(stream)
report_path=cfg["report"]
def report(data):
    with open(report_path,"w",encoding="utf-8") as stream:
        json.dump(data,stream,ensure_ascii=False)
def norm(value):
    return re.sub(r"[^a-zа-яё0-9]", "", value.casefold())
def close_enough(a,b):
    a,b=norm(a),norm(b)
    return bool(a and b and (a==b or a in b or b in a))
try:
    bpy.ops.wm.open_mainfile(filepath=cfg["source"], load_ui=False)
    cues=cfg["cues"]
    key_pattern=re.compile(r"(mouth.?open|open.?mouth|jaw.?open|рот.?открыт|открыт.?рот|челюсть.?откр)",re.I)
    candidates=[]
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data.shape_keys:
            continue
        for key in list(obj.data.shape_keys.key_blocks)[1:]:
            if key_pattern.search(key.name):
                candidates.append((obj,key))
    if not candidates:
        report({"status":"blocked","reason":"mouth_shape_key_not_found",
                "candidate_count":0,"candidate_objects":[],
                "hint":"Add or rename an existing mouth-open shape key (e.g. mouth_open or рот_открыт)."})
    else:
        speakers=sorted({c.get("speaker","").strip() for c in cues if c.get("speaker","").strip()})
        assignment={}
        used=set()
        ambiguous={}
        for speaker in speakers:
            matched=[pair for pair in candidates if close_enough(speaker,pair[0].name)]
            if not matched and len(speakers)==1 and len(candidates)==1:
                matched=candidates[:]
            if len(matched)!=1 or id(matched[0][1]) in used:
                ambiguous[speaker]=[{"object":o.name,"shape_key":k.name} for o,k in matched]
            else:
                assignment[speaker]=matched[0]
                used.add(id(matched[0][1]))
        if ambiguous:
            report({"status":"blocked","reason":"mouth_control_missing_or_ambiguous_for_speaker",
                    "speakers":speakers,"ambiguous":ambiguous,
                    "candidates":[{"object":o.name,"shape_key":k.name} for o,k in candidates]})
        else:
            blocked=[]
            for speaker,(obj,key) in assignment.items():
                ad=key.id_data.animation_data
                if ad and ad.action:
                    blocked.append({"speaker":speaker,"object":obj.name,"shape_key":key.name})
            if blocked:
                report({"status":"blocked","reason":"shape_key_animation_already_exists","controls":blocked})
            else:
                applied=0
                for cue in cues:
                    speaker=cue.get("speaker","").strip()
                    obj,key=assignment[speaker]
                    start=int(cue["frame_start"]); end=int(cue["frame_end"])
                    value=1.0 if cue["mouth"]=="open" else 0.0
                    key.value=value
                    key.keyframe_insert(data_path="value",frame=start,group="Agent Mouth Motion")
                    key.value=value
                    key.keyframe_insert(data_path="value",frame=end,group="Agent Mouth Motion")
                    applied+=1
                for obj,key in assignment.values():
                    ad=key.id_data.animation_data
                    if ad and ad.action:
                        for fc in ad.action.fcurves:
                            for point in fc.keyframe_points:
                                point.interpolation="CONSTANT"
                scene=bpy.context.scene
                scene.frame_end=max(scene.frame_end,max(int(c["frame_end"]) for c in cues))
                scene.frame_set(scene.frame_start)
                bpy.ops.wm.save_as_mainfile(filepath=cfg["output"])
                report({"status":"completed","source":cfg["source"],"output":cfg["output"],
                        "controls":[{"speaker":s,"object":o.name,"shape_key":k.name} for s,(o,k) in assignment.items()],
                        "cue_count":applied,"method":"coarse_open_close","audio_required":False})
except Exception as exc:
    report({"status":"failed","reason":"blender_script_error","error_type":type(exc).__name__})
    raise
'''


def apply_mouth_motion(project_name: str) -> dict[str, Any]:
    """Discover matching existing mouth shape keys and animate them in a safe project copy."""
    if not isinstance(project_name, str) or not _PROJECT_RE.fullmatch(project_name):
        raise ValueError("Invalid project_name.")
    executable = os.environ.get("BLENDER_EXECUTABLE", "").strip()
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not executable or not workspace_value:
        return {"status": "blocked", "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally"}
    blender = Path(executable).expanduser().resolve()
    workspace = Path(workspace_value).expanduser().resolve()
    if not blender.is_file():
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    project = (workspace / project_name).resolve()
    if not project.is_relative_to(workspace) or project == workspace or project.is_symlink():
        raise ValueError("Project path must remain inside workspace and not be a symlink.")
    preferred_sources = [project / "mia_blockout.blend", project / "project.blend", project / "scene.blend"]
    source = next((p for p in preferred_sources if p.is_file() and not p.is_symlink()), None)
    if source is None:
        existing_sources = [p for p in project.glob("*.blend") if p.is_file() and not p.is_symlink() and p.name != "mouth_motion.blend"]
        if len(existing_sources) != 1:
            return {"status": "blocked", "reason": "source_blend_missing_or_ambiguous",
                    "candidates": [p.name for p in existing_sources[:20]],
                    "hint": "Keep one source .blend in the project folder or use mia_blockout.blend, project.blend, or scene.blend."}
        source = existing_sources[0]
    manifest = project / "storyboard_compile.json"
    output = project / "mouth_motion.blend"
    report = project / "mouth_motion_result.json"
    for path in (source, manifest):
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            return {"status": "blocked", "reason": "required_source_or_storyboard_missing", "missing": path.name}
    if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (output, report)):
        raise ValueError("Mouth-motion output must not be a symlink or junction.")
    if output.exists() or report.exists():
        return {"status": "blocked", "reason": "mouth_motion_outputs_exist_refusing_to_overwrite"}
    try:
        compiled = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "blocked", "reason": "storyboard_manifest_invalid"}
    cues = compiled.get("mouth_motion", {}).get("cues", [])
    if not isinstance(cues, list) or not cues:
        return {"status": "blocked", "reason": "storyboard_contains_no_mouth_motion_cues"}
    if len(cues) > 20_000:
        return {"status": "blocked", "reason": "mouth_motion_cue_limit_exceeded"}
    for cue in cues:
        if (not isinstance(cue, dict) or not isinstance(cue.get("speaker"), str)
                or cue.get("mouth") not in {"open", "closed"}
                or isinstance(cue.get("frame_start"), bool) or not isinstance(cue.get("frame_start"), int)
                or isinstance(cue.get("frame_end"), bool) or not isinstance(cue.get("frame_end"), int)
                or cue["frame_start"] < 1 or cue["frame_end"] < cue["frame_start"]):
            return {"status": "blocked", "reason": "invalid_mouth_motion_cue"}
    # Gate speech animation on a fresh facial-rig audit of the exact source file.
    from local_agent.blender_face_rig_check import check_face_rig
    preflight = check_face_rig(
        project_name, source.name,
        report_name="face_rig_preflight_for_mouth_motion.json",
    )
    if preflight.get("status") != "ready":
        return {
            "status": "blocked",
            "reason": "facial_rig_preflight_not_ready",
            "preflight": preflight,
            "next_step": "Fix the listed rig issues and rerun face-rig-check before creating speech animation.",
        }
    supported = re.compile(r"(mouth.?open|open.?mouth|jaw.?open|рот.?открыт|открыт.?рот|челюсть.?откр)", re.I)
    supported_controls = [
        item for item in preflight.get("shape_keys", [])
        if isinstance(item, dict) and supported.search(str(item.get("control", "")))
    ]
    if not supported_controls:
        return {
            "status": "blocked",
            "reason": "no_supported_mouth_open_shape_key",
            "preflight": preflight,
            "next_step": "Add a shape key named mouth_open (or рот_открыт), then rerun the face-rig check.",
        }
    cfg = {"source": str(source), "output": str(output), "report": str(report), "cues": cues}
    try:
        with tempfile.TemporaryDirectory(prefix=".mouth-motion-", dir=project) as temp:
            cfg_path = Path(temp) / "mouth_motion_task.json"
            script_path = Path(temp) / "mouth_motion_task.py"
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
            script_path.write_text(_blender_script(), encoding="utf-8")
            proc = subprocess.run(
                [str(blender), "--disable-autoexec", "--background", "--python", str(script_path), "--", str(cfg_path)],
                cwd=str(project), capture_output=True, text=True, timeout=600, check=False, shell=False,
            )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "mouth_motion_blender_timeout"}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}
    if not report.is_file() or report.is_symlink():
        return {"status": "failed", "reason": "mouth_motion_report_missing", "return_code": proc.returncode}
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "failed", "reason": "mouth_motion_report_invalid"}
    if data.get("status") != "completed":
        return {**data, "task": "blender_mouth_motion"}
    if proc.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        return {"status": "failed", "reason": "mouth_motion_output_missing_or_blender_failed"}
    return {"status": "completed", "task": "blender_mouth_motion", "output_path": str(output),
            "controls": data["controls"], "cue_count": data["cue_count"],
            "note": "Original project preserved. Inspect the resulting animation in Blender before production use."}
