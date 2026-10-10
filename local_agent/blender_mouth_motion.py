"""Apply coarse dialogue mouth cues to an existing Blender shape key, saving a copy."""
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
import bpy, json, os, re, sys
from pathlib import Path
args=sys.argv[sys.argv.index("--")+1:]
cfg=json.load(open(args[0],encoding="utf-8"))
report_path=cfg["report"]
def report(data):
    with open(report_path,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False)
try:
    bpy.ops.wm.open_mainfile(filepath=cfg["source"], load_ui=False)
    cues=cfg["cues"]
    # Keep the first prototype deliberately simple: one existing open/close shape key.
    key_pattern=re.compile(r"(mouth.?open|open.?mouth|jaw.?open|рот.?открыт|открыт.?рот|челюсть.?откр)",re.I)
    def norm(value):
        return re.sub(r"[^a-zа-яё0-9]", "", value.casefold())
    speakers={norm(c.get("speaker","")) for c in cues if c.get("speaker")}
    candidates=[]
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data.shape_keys:
            continue
        blocks=obj.data.shape_keys.key_blocks
        for key in list(blocks)[1:]:
            if key_pattern.search(key.name):
                candidates.append((obj,key))
    if speakers:
        matched=[pair for pair in candidates if any(s and (s in norm(pair[0].name) or norm(pair[0].name) in s) for s in speakers)]
        if matched:
            candidates=matched
    # A unique candidate is a safe fallback when prompt speaker naming differs
    # from the Blender object's name (e.g. Cyrillic vs Latin).
    if len(candidates) != 1:
        report({"status":"blocked","reason":"mouth_shape_key_not_found_or_ambiguous",
                "candidate_count":len(candidates),"candidate_objects":[o.name for o,k in candidates],
                "required_shape_key_names":["mouth_open","jaw_open","рот_открыт"]})
    else:
        obj,key=candidates[0]
        if key.id_data.animation_data and key.id_data.animation_data.action:
            report({"status":"blocked","reason":"shape_key_animation_already_exists",
                    "object":obj.name,"shape_key":key.name})
        else:
            for cue in cues:
                start=int(cue["frame_start"]); end=int(cue["frame_end"])
                value=1.0 if cue["mouth"]=="open" else 0.0
                key.value=value
                key.keyframe_insert(data_path="value",frame=start,group="Agent Mouth Motion")
                key.value=value
                key.keyframe_insert(data_path="value",frame=end,group="Agent Mouth Motion")
            if key.id_data.animation_data and key.id_data.animation_data.action:
                for fc in key.id_data.animation_data.action.fcurves:
                    for point in fc.keyframe_points:
                        point.interpolation="CONSTANT"
            scene=bpy.context.scene
            scene.frame_end=max(scene.frame_end,max(int(c["frame_end"]) for c in cues))
            scene.frame_set(scene.frame_start)
            bpy.ops.wm.save_as_mainfile(filepath=cfg["output"])
            report({"status":"completed","source":cfg["source"],"output":cfg["output"],
                    "object":obj.name,"shape_key":key.name,"cue_count":len(cues),
                    "method":"coarse_open_close","audio_required":False})
except Exception as exc:
    report({"status":"failed","reason":"blender_script_error","error_type":type(exc).__name__})
    raise
'''


def apply_mouth_motion(project_name: str) -> dict[str, Any]:
    """Read the compiled storyboard and animate a discovered mouth-open shape key."""
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
    source = project / "mia_blockout.blend"
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
        if (not isinstance(cue, dict) or cue.get("mouth") not in {"open", "closed"}
                or isinstance(cue.get("frame_start"), bool) or not isinstance(cue.get("frame_start"), int)
                or isinstance(cue.get("frame_end"), bool) or not isinstance(cue.get("frame_end"), int)
                or cue["frame_start"] < 1 or cue["frame_end"] < cue["frame_start"]):
            return {"status": "blocked", "reason": "invalid_mouth_motion_cue"}
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
            "object": data["object"], "shape_key": data["shape_key"], "cue_count": data["cue_count"],
            "note": "Original project preserved. Inspect the resulting animation in Blender before production use."}
