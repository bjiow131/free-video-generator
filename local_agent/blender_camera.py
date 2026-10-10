"""Typed, bounded camera control for an existing local Blender project.

Remote arguments are enums and bounded numbers only. The original .blend is
opened read-only in practice and saved to a new, collision-safe output file.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
PRESETS = {
    "establishing_wide": {"lens": 28.0, "distance": 9.0, "height": 0.65},
    "medium_shot": {"lens": 50.0, "distance": 5.2, "height": 0.58},
    "close_up": {"lens": 72.0, "distance": 3.2, "height": 0.62},
    "portrait_vertical": {"lens": 50.0, "distance": 5.0, "height": 0.58},
    "low_angle": {"lens": 40.0, "distance": 6.2, "height": 0.22},
    "high_angle": {"lens": 40.0, "distance": 6.2, "height": 0.88},
}
MOVES = {"static", "push_in", "pull_out", "pan_left", "pan_right", "orbit"}
def _safe_project(project_name: str) -> str:
    if not isinstance(project_name, str) or not PROJECT_RE.fullmatch(project_name):
        raise ValueError("Invalid project_name.")
    return project_name

def _script() -> str:
    return r'''
import bpy, json, math, os, sys
from mathutils import Vector
args=sys.argv[sys.argv.index("--")+1:]
cfg=json.load(open(args[0],encoding="utf-8"))
src=os.path.realpath(cfg["source"])
out=os.path.realpath(cfg["output"])
report=os.path.realpath(cfg["report"])
preview=os.path.realpath(cfg["preview"])
bpy.ops.wm.open_mainfile(filepath=src, load_ui=False)
scene=bpy.context.scene
preset=cfg["preset"]; move=cfg["move"]
# Target the bounding-box center of visible mesh objects; fall back to origin.
points=[]
for obj in scene.objects:
    if obj.type=="MESH" and obj.visible_get():
        try: points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
        except Exception: pass
target=sum(points,Vector((0,0,0)))/len(points) if points else Vector((0,0,1))
if not points: target=Vector((0,0,1))
spec=cfg["spec"]
distance=spec["distance"]
camera=scene.camera
if camera is None:
    bpy.ops.object.camera_add()
    camera=bpy.context.object
    camera.name="Agent Camera"
scene.camera=camera
camera.data.lens=spec["lens"]
camera.data.type="PERSP"
def point_at(obj, point):
    direction=Vector(point)-obj.location
    if direction.length < 1e-6: raise RuntimeError("Camera target coincides with camera")
    obj.rotation_euler=direction.to_track_quat("-Z","Y").to_euler()
start=target+Vector((distance,-distance*1.25,max(0.8,distance*spec["height"])))
end=start.copy()
if move=="push_in": end=target+(start-target)*0.72
elif move=="pull_out": end=target+(start-target)*1.28
elif move=="pan_left": end.x-=distance*0.22
elif move=="pan_right": end.x+=distance*0.22
elif move=="orbit":
    offset=start-target
    angle=math.radians(18)
    end=target+Vector((offset.x*math.cos(angle)-offset.y*math.sin(angle),
                       offset.x*math.sin(angle)+offset.y*math.cos(angle),offset.z))
scene.frame_start=max(1,scene.frame_start)
frames=cfg["frames"]
scene.frame_end=max(scene.frame_start+frames-1,scene.frame_end)
# Preserve any existing camera animation by making the output camera single-user.
if camera.data.users>1: camera.data=camera.data.copy()
camera.animation_data_clear()
for frame,loc in ((scene.frame_start,start),(scene.frame_start+frames-1,end)):
    camera.location=loc
    point_at(camera,target + (Vector((0.10,0,0)) if move=="pan_left" else Vector((-0.10,0,0)) if move=="pan_right" else Vector((0,0,0)))
    camera.keyframe_insert(data_path="location",frame=frame,group="Agent Camera Move")
    camera.keyframe_insert(data_path="rotation_euler",frame=frame,group="Agent Camera Move")
if camera.animation_data and camera.animation_data.action:
    for fc in camera.animation_data.action.fcurves:
        for key in fc.keyframe_points: key.interpolation="BEZIER"
scene.frame_set(scene.frame_start)
original_settings=(scene.render.resolution_x,scene.render.resolution_y,scene.render.resolution_percentage,scene.render.filepath)
scene.render.image_settings.file_format="PNG"
scene.render.filepath=preview
scene.render.resolution_percentage=min(scene.render.resolution_percentage,50)
bpy.ops.wm.save_as_mainfile(filepath=out)
bpy.ops.render.render(write_still=True)
scene.render.resolution_x,scene.render.resolution_y,scene.render.resolution_percentage,scene.render.filepath=original_settings
bpy.ops.wm.save_as_mainfile(filepath=out)
data={"status":"completed","source":src,"output":out,"preview":preview,
      "camera":camera.name,"preset":preset,"move":move,"frames":[scene.frame_start,scene.frame_start+frames-1],
      "lens_mm":camera.data.lens,"resolution":[scene.render.resolution_x,scene.render.resolution_y],
      "camera_created":True if camera.name=="Agent Camera" else False}
json.dump(data,open(report,"w",encoding="utf-8"),ensure_ascii=False)
'''

def control_camera(project_name: str, *, preset: str, move: str = "static",
                   frames: int = 48, create_camera_if_missing: bool = True) -> dict[str, Any]:
    """Apply a typed camera preset/move to an existing project and save a copy."""
    project_name = _safe_project(project_name)
    if preset not in PRESETS:
        raise ValueError("Unsupported camera preset.")
    if move not in MOVES:
        raise ValueError("Unsupported camera move.")
    if isinstance(frames, bool) or not isinstance(frames, int) or not 2 <= frames <= 240:
        raise ValueError("frames must be an integer from 2 to 240.")
    if not isinstance(create_camera_if_missing, bool):
        raise ValueError("create_camera_if_missing must be boolean.")
    executable=os.environ.get("BLENDER_EXECUTABLE","").strip()
    workspace_value=os.environ.get("LOCAL_AGENT_WORKSPACE","").strip()
    if not executable or not workspace_value:
        return {"status":"blocked","reason":"set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally"}
    blender=Path(executable).expanduser().resolve()
    workspace=Path(workspace_value).expanduser().resolve()
    if not blender.is_file(): return {"status":"blocked","reason":"blender_executable_not_found"}
    project=(workspace/project_name).resolve()
    if not project.is_relative_to(workspace) or project==workspace or project.is_symlink():
        raise ValueError("Project path must remain inside workspace and not be a symlink.")
    source=project/"mia_blockout.blend"
    if not source.is_file() or source.is_symlink() or source.stat().st_size==0:
        return {"status":"blocked","reason":"valid_mia_blockout_project_not_found","project_dir":str(project)}
    suffix=f"camera_{preset}_{move}"
    output=project/f"{suffix}.blend"; preview=project/f"{suffix}.png"; report=project/f"{suffix}.json"
    outputs=(output,preview,report)
    if any(p.is_symlink() or getattr(p,"is_junction",lambda:False)() for p in outputs):
        raise ValueError("Camera output must not be a symlink or junction.")
    if any(p.exists() for p in outputs):
        return {"status":"blocked","reason":"camera_outputs_exist; refusing_to_overwrite","project_dir":str(project)}
    cfg={"source":str(source),"output":str(output),"preview":str(preview),"report":str(report),
         "preset":preset,"move":move,"frames":frames,"spec":PRESETS[preset],
         "create_camera_if_missing":create_camera_if_missing}
    # Fail closed on a missing camera unless caller explicitly allows creation.
    check_script='import bpy,sys; p=sys.argv[sys.argv.index("--")+1]; bpy.ops.wm.open_mainfile(filepath=p,load_ui=False); s=bpy.context.scene; print("AGENT_CAMERA_PRESENT="+str(s.camera is not None)); print("AGENT_CAMERA_ANIMATED="+str(bool(s.camera and s.camera.animation_data)))'
    try:
        check=subprocess.run([str(blender),"--disable-autoexec","--background",
                              "--python-expr",check_script,"--",str(source)],capture_output=True,text=True,
                             timeout=90,check=False,shell=False,cwd=str(project))
        if check.returncode!=0:
            return {"status":"failed","reason":"source_project_preflight_failed","stderr_tail":(check.stderr or "")[-1500:]}
        has_camera="AGENT_CAMERA_PRESENT=True" in (check.stdout or "")
        has_animation="AGENT_CAMERA_ANIMATED=True" in (check.stdout or "")
        if has_animation:
            return {"status":"blocked","reason":"active_camera_has_animation; refusing_to_replace_existing_animation"}
        if not has_camera and not create_camera_if_missing:
            return {"status":"blocked","reason":"source_project_has_no_active_camera"}
        with tempfile.TemporaryDirectory(prefix=".camera-control-",dir=project) as temp:
            cfg_path=Path(temp)/"camera_task.json"
            script_path=Path(temp)/"camera_task.py"
            cfg_path.write_text(json.dumps(cfg,ensure_ascii=False),encoding="utf-8")
            script_path.write_text(_script(),encoding="utf-8")
            proc=subprocess.run([str(blender),"--disable-autoexec","--background","--factory-startup",
                                 "--python",str(script_path),"--",str(cfg_path)],
                                cwd=str(project),capture_output=True,text=True,timeout=600,
                                check=False,shell=False)
    except subprocess.TimeoutExpired:
        return {"status":"timeout","reason":"camera_control_timeout"}
    except OSError as exc:
        return {"status":"error","error_type":type(exc).__name__}
    if proc.returncode!=0:
        return {"status":"failed","reason":"camera_control_blender_failed",
                "return_code":proc.returncode,"stderr_tail":(proc.stderr or "")[-2000:]}
    if not output.is_file() or output.stat().st_size==0 or not preview.is_file() or preview.stat().st_size<24 or not report.is_file():
        return {"status":"failed","reason":"camera_outputs_missing_or_empty"}
    try: data=json.loads(report.read_text(encoding="utf-8"))
    except (OSError,ValueError): return {"status":"failed","reason":"camera_report_invalid"}
    if data.get("status")!="completed" or data.get("source")!=str(source) or data.get("output")!=str(output):
        return {"status":"failed","reason":"camera_report_validation_failed"}
    return {"status":"completed","task":"blender_camera_control","project_dir":str(project),
            "output_path":str(output),"preview_path":str(preview),"report_path":str(report),
            "preset":preset,"move":move,"frames":frames,
            "note":"Original project preserved. Inspect the preview and camera motion in Blender before production use."}
