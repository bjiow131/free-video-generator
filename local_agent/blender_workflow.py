"""Bounded Blender workflow helpers for local discovery and Mia blockout creation.

All Blender scripts are bundled here as fixed code. Remote task arguments are
validated data only; no task can provide Python source, shell commands, or paths.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import zlib
from typing import Any


class BlenderWorkflowError(RuntimeError):
    """A safe Blender discovery or workflow operation failed."""


def discover_blender() -> dict[str, Any]:
    """Find Blender from local configuration/PATH and query its version."""
    configured = os.environ.get("BLENDER_EXECUTABLE", "").strip()
    candidate = Path(configured).expanduser() if configured else None
    source = "environment" if candidate else "path"
    if candidate is None:
        found = shutil.which("blender.exe") or shutil.which("blender")
        candidate = Path(found) if found else None
    if candidate is None or not candidate.is_file():
        return {"status": "needs_setup", "available": False,
                "configured": bool(configured), "reason": "blender_executable_not_found"}
    try:
        proc = subprocess.run([str(candidate.resolve()), "--version"],
                              capture_output=True, text=True, timeout=15,
                              check=False, shell=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "available": False,
                "error_type": type(exc).__name__, "path_source": source}
    lines = (proc.stdout or proc.stderr).splitlines()
    version_line = lines[0][:240] if lines else "version output unavailable"
    return {"status": "ready" if proc.returncode == 0 else "error",
            "available": proc.returncode == 0, "path": str(candidate.resolve()),
            "path_source": source, "return_code": proc.returncode,
            "version": version_line}


def _scene_script() -> str:
    """Fixed, self-contained stylized blockout of Mia plus her recurring props."""
    return r'''
import bpy, json, math, os, sys
from mathutils import Vector
args = sys.argv[sys.argv.index("--") + 1:]
with open(args[0], "r", encoding="utf-8") as f:
    cfg = json.load(f)
out = os.path.realpath(cfg["output_dir"])
os.makedirs(out, exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

def mat(name, color, roughness=0.72):
    m = bpy.data.materials.new(name); m.diffuse_color = (*color, 1)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1)
        bsdf.inputs["Roughness"].default_value = roughness
    return m

skin=mat("Mia | warm skin",(0.78,0.49,0.32))
hair=mat("Mia | chestnut hair",(0.12,0.045,0.025))
dress=mat("Mia | teal dress",(0.12,0.42,0.39))
shoe=mat("Mia | dark shoes",(0.09,0.07,0.06))
white=mat("Eyes | ivory",(0.95,0.88,0.73))
iris=mat("Eyes | brown",(0.19,0.08,0.035))
yellow=mat("Scooter | sunny yellow",(1.0,0.62,0.05),0.38)
metal=mat("Scooter | metal",(0.20,0.23,0.24),0.4)
snail=mat("Snail | soft green",(0.35,0.53,0.27))
shell=mat("Snail | amber shell",(0.67,0.31,0.12))
groundmat=mat("Ground | warm neutral",(0.26,0.30,0.25))
def uv(name, loc, scale, material, segments=24, rings=16):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings, location=loc)
    o=bpy.context.object; o.name=name; o.scale=scale; o.data.materials.append(material)
    bpy.ops.object.shade_smooth(); return o
def cyl(name, loc, radius, depth, material, vertices=16):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    o=bpy.context.object; o.name=name; o.data.materials.append(material); return o
def between(name, a, b, radius, material):
    mid=(Vector(a)+Vector(b))/2; vec=Vector(b)-Vector(a)
    o=cyl(name,mid,radius,vec.length,material)
    o.rotation_euler=vec.to_track_quat("Z","Y").to_euler()
    return o
# Mia: deliberately simple, editable proportions; not a finished production mesh.
uv("Mia | head",(0,0,3.12),(0.53,0.47,0.58),skin)
uv("Mia | hair cap",(0,0.035,3.48),(0.55,0.48,0.32),hair)
uv("Mia | back hair",(0,0.23,3.13),(0.48,0.28,0.62),hair)
uv("Mia | fringe left",(-0.24,-0.405,3.43),(0.25,0.12,0.19),hair)
uv("Mia | fringe right",(0.08,-0.425,3.45),(0.24,0.11,0.17),hair)
for x in (-0.19,0.19):
    uv("Mia | eye white",(x,-0.438,3.17),(0.09,0.045,0.105),white,20,12)
    uv("Mia | iris",(x,-0.478,3.16),(0.044,0.022,0.058),iris,16,10)
uv("Mia | nose",(0,-0.49,3.02),(0.045,0.04,0.05),skin,16,10)
uv("Mia | torso",(0,0,2.22),(0.37,0.27,0.57),dress)
uv("Mia | skirt",(0,0,1.88),(0.48,0.34,0.24),dress)
uv("Mia | neck",(0,0,2.77),(0.13,0.13,0.17),skin)
for side in (-1,1):
    hip=(side*0.19,0,1.72); knee=(side*0.21,-0.015,1.05); ankle=(side*0.22,-0.02,0.48)
    between("Mia | leg",hip,knee,0.105,skin); between("Mia | lower leg",knee,ankle,0.085,skin)
    uv("Mia | shoe",(side*0.22,-0.10,0.34),(0.15,0.24,0.10),shoe)
    shoulder=(side*0.32,0,2.55); elbow=(side*0.48,-0.015,2.22); hand=(side*0.52,-0.04,2.03)
    between("Mia | upper arm",shoulder,elbow,0.105,skin); between("Mia | forearm",elbow,hand,0.075,skin)
    uv("Mia | hand",hand,(0.09,0.08,0.10),skin)
# Yellow scooter to preserve the character bible.
between("Scooter | deck",(-0.2,-0.72,0.35),(0.62,-0.72,0.35),0.055,yellow)
for x in (-0.12,0.55):
    o=cyl("Scooter | wheel",(x,-0.72,0.20),0.13,0.09,shoe,24); o.rotation_euler[0]=math.pi/2
between("Scooter | stem",(0.52,-0.72,0.35),(0.57,-0.72,0.93),0.035,metal)
between("Scooter | handle", (0.42,-0.72,0.93),(0.72,-0.72,0.93),0.035,yellow)
# Friendly stylized snail companion.
uv("Snail | body",(1.55,-0.1,0.25),(0.42,0.20,0.16),snail)
uv("Snail | head",(1.84,-0.1,0.43),(0.14,0.14,0.21),snail)
uv("Snail | shell",(1.49,-0.11,0.48),(0.27,0.25,0.27),shell)
for x in (1.79,1.91):
    between("Snail | eye stalk",(x,-0.1,0.55),(x,-0.1,0.67),0.025,snail)
    uv("Snail | eye",(x,-0.13,0.69),(0.035,0.03,0.04),white,12,8)
# Ground, camera and lights.
bpy.ops.mesh.primitive_plane_add(size=12, location=(0,0,0.02))
bpy.context.object.name="Stage | ground"; bpy.context.object.data.materials.append(groundmat)
bpy.ops.object.camera_add(location=(5,-9,4.6)); cam=bpy.context.object; cam.name="Camera | Mia blockout"
target=Vector((0.55,0,1.75)); cam.rotation_euler=(target-cam.location).to_track_quat("-Z","Y").to_euler()
cam.data.lens=52; bpy.context.scene.camera=cam
bpy.ops.object.light_add(type="AREA",location=(-3,-4,7)); key=bpy.context.object
key.data.energy=900; key.data.shape="DISK"; key.data.size=5
key.rotation_euler=(Vector((0,0,1.8))-key.location).to_track_quat("-Z","Y").to_euler()
bpy.ops.object.light_add(type="AREA",location=(4,2,5)); fill=bpy.context.object
fill.data.energy=550; fill.data.size=4
fill.rotation_euler=(Vector((0,0,1.8))-fill.location).to_track_quat("-Z","Y").to_euler()
scene=bpy.context.scene
engine_ids={i.identifier for i in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
scene.render.engine="BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engine_ids else "BLENDER_EEVEE"
scene.render.resolution_x=720; scene.render.resolution_y=1280; scene.render.resolution_percentage=50
scene.render.image_settings.file_format="PNG"; scene.render.filepath=os.path.join(out,"mia_blockout.png")
scene.world.color=(0.08,0.08,0.08)
blend=os.path.join(out,"mia_blockout.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend)
bpy.ops.render.render(write_still=True)
with open(os.path.join(out,"blender_result.json"),"w",encoding="utf-8") as f:
    json.dump({"status":"completed","blend_path":blend,"preview_path":scene.render.filepath,
               "resolution":[720,1280],"engine":scene.render.engine,
               "object_count":len(bpy.context.scene.objects),"stage":"blockout"},f)
'''



def _validate_png(path: Path, expected_size: tuple[int, int]) -> tuple[bool, str, list[int] | None]:
    """Validate PNG chunk boundaries, CRCs, required chunks, and expected dimensions."""
    try:
        with path.open("rb") as stream:
            if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                return False, "preview_is_not_png", None
            dimensions: list[int] | None = None
            saw_idat = False
            while True:
                raw_length = stream.read(4)
                if len(raw_length) != 4:
                    return False, "png_chunk_length_truncated", dimensions
                length = struct.unpack(">I", raw_length)[0]
                if length > 128 * 1024 * 1024:
                    return False, "png_chunk_exceeds_safety_limit", dimensions
                chunk_type = stream.read(4)
                if len(chunk_type) != 4:
                    return False, "png_chunk_type_truncated", dimensions
                payload = stream.read(length)
                raw_crc = stream.read(4)
                if len(payload) != length or len(raw_crc) != 4:
                    return False, "png_chunk_truncated", dimensions
                expected_crc = struct.unpack(">I", raw_crc)[0]
                actual_crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
                if actual_crc != expected_crc:
                    return False, "png_chunk_crc_mismatch", dimensions
                if chunk_type == b"IHDR":
                    if dimensions is not None or length != 13:
                        return False, "png_ihdr_invalid", dimensions
                    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
                    if width < 1 or height < 1 or bit_depth not in {1, 2, 4, 8, 16} or color_type not in {0, 2, 3, 4, 6} or compression != 0 or filtering != 0 or interlace not in {0, 1}:
                        return False, "png_ihdr_fields_invalid", None
                    dimensions = [width, height]
                elif chunk_type == b"IDAT":
                    if dimensions is None:
                        return False, "png_idat_order_invalid", dimensions
                    saw_idat = True
                elif chunk_type == b"IEND":
                    if length != 0 or not saw_idat or dimensions is None:
                        return False, "png_iend_invalid", dimensions
                    if stream.read(1):
                        return False, "png_trailing_data", dimensions
                    break
                elif not (chunk_type[0] & 0x20) and chunk_type not in {b"IHDR", b"PLTE"}:
                    return False, "png_unknown_critical_chunk", dimensions
            if dimensions != list(expected_size):
                return False, "png_dimensions_mismatch", dimensions
            return True, "ok", dimensions
    except OSError:
        return False, "preview_unreadable", None


def create_mia_blockout(project_name: str, *, overwrite: bool = False) -> dict[str, Any]:
    """Create a fixed Mia character/prop blockout, save .blend, and validate preview."""
    if not isinstance(project_name, str) or not project_name or len(project_name) > 48:
        raise BlenderWorkflowError("Invalid project name.")
    import re
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", project_name):
        raise BlenderWorkflowError("Project name must contain only letters, digits, underscores, or hyphens.")
    executable = os.environ.get("BLENDER_EXECUTABLE", "").strip()
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not executable or not workspace_value:
        return {"status": "blocked", "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally"}
    blender = Path(executable).expanduser().resolve()
    workspace = Path(workspace_value).expanduser().resolve()
    if not blender.is_file():
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    workspace.mkdir(parents=True, exist_ok=True)
    project = (workspace / project_name).resolve()
    if not project.is_relative_to(workspace) or project == workspace:
        raise BlenderWorkflowError("Project output must stay inside workspace.")
    if project.is_symlink() or getattr(project, "is_junction", lambda: False)():
        raise BlenderWorkflowError("Project folder must not be a symlink or junction.")
    project.mkdir(parents=True, exist_ok=True)
    outputs = [project / "mia_blockout.blend", project / "mia_blockout.png", project / "blender_result.json"]
    if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in outputs):
        raise BlenderWorkflowError("Output files must not be symlinks or junctions.")
    if not overwrite and any(p.exists() for p in outputs):
        return {"status": "blocked", "reason": "outputs_exist; explicit overwrite required", "project_dir": str(project)}
    if overwrite:
        for p in outputs:
            if p.exists():
                if not p.is_file():
                    raise BlenderWorkflowError("Existing output is not a regular file.")
                p.unlink()
    import tempfile
    with tempfile.TemporaryDirectory(prefix=".mia-blockout-", dir=project) as temp:
        temp_dir = Path(temp)
        script = temp_dir / "mia_blockout.py"
        cfg = temp_dir / "task.json"
        script.write_text(_scene_script(), encoding="utf-8")
        cfg.write_text(json.dumps({"output_dir": str(project)}, ensure_ascii=False), encoding="utf-8")
        try:
            proc = subprocess.run([str(blender), "--background", "--factory-startup",
                                   "--python", str(script), "--", str(cfg)],
                                  cwd=str(project), capture_output=True, text=True,
                                  timeout=1200, check=False, shell=False)
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "reason": "blender_blockout_timeout", "project_dir": str(project)}
        except OSError as exc:
            return {"status": "error", "error_type": type(exc).__name__}
    (project / "blender_stdout.log").write_text((proc.stdout or "")[-262144:], encoding="utf-8")
    (project / "blender_stderr.log").write_text((proc.stderr or "")[-262144:], encoding="utf-8")
    if proc.returncode != 0:
        return {"status": "failed", "reason": "blender_exit_nonzero", "return_code": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-3000:], "project_dir": str(project)}
    manifest = project / "blender_result.json"
    blend = project / "mia_blockout.blend"
    preview = project / "mia_blockout.png"
    if not manifest.is_file() or not blend.is_file() or blend.stat().st_size == 0 or not preview.is_file() or preview.stat().st_size < 24:
        return {"status": "failed", "reason": "expected_outputs_missing_or_empty", "project_dir": str(project)}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "failed", "reason": "output_manifest_unreadable", "project_dir": str(project)}
    png_ok, png_reason, dimensions = _validate_png(preview, (360, 640))
    if not png_ok:
        return {"status": "failed", "reason": png_reason, "project_dir": str(project)}
    if data.get("status") != "completed" or data.get("stage") != "blockout":
        return {"status": "failed", "reason": "output_manifest_validation_failed", "project_dir": str(project)}
    return {"status": "completed", "task": "blender_mia_blockout", "stage": "blockout",
            "project_dir": str(project), "blend_path": str(blend), "preview_path": str(preview),
            "resolution": dimensions, "object_count": data.get("object_count"),
            "engine": data.get("engine"), "manual_review_required": True,
            "note": "Starter blockout only; not a finished or rigged production character."}


def open_mia_project(project_name: str) -> dict[str, Any]:
    """Open an existing generated Mia project in Blender's GUI without UI clicks."""
    import re
    if not isinstance(project_name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", project_name):
        raise BlenderWorkflowError("Project name must contain only letters, digits, underscores, or hyphens.")
    executable = os.environ.get("BLENDER_EXECUTABLE", "").strip()
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not executable or not workspace_value:
        return {"status": "blocked", "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally"}
    blender = Path(executable).expanduser().resolve()
    workspace = Path(workspace_value).expanduser().resolve()
    project_dir = (workspace / project_name).resolve()
    if not project_dir.is_relative_to(workspace) or project_dir == workspace:
        raise BlenderWorkflowError("Project path must stay inside workspace.")
    blend = project_dir / "mia_blockout.blend"
    if not blender.is_file():
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    if project_dir.is_symlink() or getattr(project_dir, "is_junction", lambda: False)():
        raise BlenderWorkflowError("Project folder must not be a symlink or junction.")
    if blend.is_symlink() or not blend.is_file() or blend.stat().st_size == 0:
        return {"status": "blocked", "reason": "valid_mia_blockout_project_not_found", "project_dir": str(project_dir)}
    try:
        kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                                  "stderr": subprocess.DEVNULL, "close_fds": True}
        if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen([str(blender), str(blend)], cwd=str(project_dir),
                                   shell=False, **kwargs)
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}
    return {"status": "started", "project_path": str(blend),
            "process_id": getattr(process, "pid", None),
            "note": "Blender GUI launch requested; visual inspection is still required."}


def inspect_mia_project(project_name: str) -> dict[str, Any]:
    """Inspect a generated project with a bundled read-only Blender script."""
    import re
    if not isinstance(project_name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", project_name):
        raise BlenderWorkflowError("Project name must contain only letters, digits, underscores, or hyphens.")
    executable = os.environ.get("BLENDER_EXECUTABLE", "").strip()
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not executable or not workspace_value:
        return {"status": "blocked", "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally"}
    blender = Path(executable).expanduser().resolve()
    workspace = Path(workspace_value).expanduser().resolve()
    project_dir = (workspace / project_name).resolve()
    blend = project_dir / "mia_blockout.blend"
    if not blender.is_file():
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    if not project_dir.is_relative_to(workspace) or project_dir == workspace or project_dir.is_symlink():
        raise BlenderWorkflowError("Project path must be a real folder inside workspace.")
    if blend.is_symlink() or not blend.is_file() or blend.stat().st_size == 0:
        return {"status": "blocked", "reason": "valid_mia_blockout_project_not_found"}
    import tempfile
    script_text = r'''
import bpy, json, os, sys
args=sys.argv[sys.argv.index("--")+1:]
blend_path=os.path.realpath(args[0]); report_path=os.path.realpath(args[1])
bpy.ops.wm.open_mainfile(filepath=blend_path, load_ui=False)
scene=bpy.context.scene
missing=[]
for image in bpy.data.images:
    if image.source == "FILE" and image.filepath:
        resolved=bpy.path.abspath(image.filepath)
        if not os.path.exists(resolved):
            missing.append(os.path.basename(image.filepath))
data={
 "status":"completed",
 "scene_name":scene.name,
 "object_count":len(scene.objects),
 "mesh_count":sum(1 for o in scene.objects if o.type=="MESH"),
 "camera_count":sum(1 for o in scene.objects if o.type=="CAMERA"),
 "light_count":sum(1 for o in scene.objects if o.type=="LIGHT"),
 "material_count":len(bpy.data.materials),
 "camera_assigned":scene.camera is not None,
 "render_resolution":[scene.render.resolution_x,scene.render.resolution_y],
 "render_engine":scene.render.engine,
 "missing_image_files":missing,
 "object_names":[o.name for o in list(scene.objects)[:250]],
 "blend_path":blend_path
}
with open(report_path,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False)
'''
    report = project_dir / "mia_inspection.json"
    if report.is_symlink():
        raise BlenderWorkflowError("Inspection report path must not be a symlink.")
    try:
        with tempfile.TemporaryDirectory(prefix=".mia-inspect-", dir=project_dir) as temp:
            script = Path(temp) / "inspect.py"
            script.write_text(script_text, encoding="utf-8")
            proc = subprocess.run([str(blender), "--disable-autoexec", "--background",
                                   "--factory-startup", "--python", str(script), "--",
                                   str(blend), str(report)],
                                  cwd=str(project_dir), capture_output=True, text=True,
                                  timeout=180, check=False, shell=False)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "blender_inspection_timeout"}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}
    if proc.returncode != 0 or not report.is_file() or report.stat().st_size == 0:
        return {"status": "failed", "reason": "blender_inspection_failed",
                "return_code": proc.returncode, "stderr_tail": (proc.stderr or "")[-2000:]}
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "failed", "reason": "inspection_report_unreadable"}
    if data.get("status") != "completed" or data.get("blend_path") != str(blend):
        return {"status": "failed", "reason": "inspection_report_validation_failed"}
    return {"status": "completed", "task": "blender_inspect_mia_project", "inspection": data,
            "note": "Structural inspection only; it does not judge visual quality."}
