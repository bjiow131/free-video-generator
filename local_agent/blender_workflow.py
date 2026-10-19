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

from local_agent.blender_locator import find_blender_executable
from local_agent.path_names import path_identifier_pattern, is_link_or_junction

_PROJECT_NAME = path_identifier_pattern(48)


class BlenderWorkflowError(RuntimeError):
    """A safe Blender discovery or workflow operation failed."""


def discover_blender() -> dict[str, Any]:
    """Find Blender from local configuration/PATH and query its version."""
    configured = os.environ.get("BLENDER_EXECUTABLE", "").strip()
    candidate = find_blender_executable()
    source = "environment" if configured else "installed_or_path"
    if candidate is None or not candidate.is_file():
        return {"status": "needs_setup", "available": False,
                "configured": bool(configured), "reason": "blender_executable_not_found"}
    try:
        proc = subprocess.run([str(candidate.resolve()), "--version"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
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
    if not _PROJECT_NAME.fullmatch(project_name):
        raise BlenderWorkflowError("Project name must contain only letters, digits, underscores, or hyphens.")
    blender = find_blender_executable()
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not workspace_value:
        return {"status": "blocked", "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally"}
    if blender is None:
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    workspace = Path(workspace_value).expanduser().resolve()
    if not blender.is_file():
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    workspace.mkdir(parents=True, exist_ok=True)
    project = workspace / project_name
    if is_link_or_junction(project):
        raise BlenderWorkflowError("Project folder must not be a symlink or junction.")
    project = project.resolve()
    if not project.is_relative_to(workspace) or project == workspace:
        raise BlenderWorkflowError("Project output must stay inside workspace.")
    if is_link_or_junction(project):
        raise BlenderWorkflowError("Project folder must not be a symlink or junction.")
    project.mkdir(parents=True, exist_ok=True)
    outputs = [project / "mia_blockout.blend", project / "mia_blockout.png", project / "blender_result.json"]
    if any(is_link_or_junction(p) for p in outputs + [project / "blender_stdout.log", project / "blender_stderr.log"]):
        raise BlenderWorkflowError("Output files must not be symlinks or junctions.")
    if not overwrite and any(p.exists() for p in outputs):
        return {"status": "blocked", "reason": "outputs_exist; explicit overwrite required", "project_dir": str(project)}
    import tempfile
    backup_dir = None
    existing = [path for path in outputs if path.exists()]
    if overwrite and existing:
        if any(not path.is_file() for path in existing):
            raise BlenderWorkflowError("Existing output is not a regular file.")
        backup_dir = Path(tempfile.mkdtemp(prefix=".mia-backup-", dir=workspace))
        # Complete every copy before touching any original.
        for path in existing:
            shutil.copy2(path, backup_dir / path.name)

    def generate() -> dict[str, Any]:
        if overwrite:
            for path in outputs:
                path.unlink(missing_ok=True)
        import tempfile
        with tempfile.TemporaryDirectory(prefix=".mia-blockout-", dir=project) as temp:
            temp_dir = Path(temp)
            script = temp_dir / "mia_blockout.py"
            cfg = temp_dir / "task.json"
            script.write_text(_scene_script(), encoding="utf-8")
            cfg.write_text(json.dumps({"output_dir": str(project)}, ensure_ascii=False), encoding="utf-8")
            try:
                proc = subprocess.run([str(blender), "--background", "--factory-startup", "--disable-autoexec", "--python-exit-code", "1",
                                       "--python", str(script), "--", str(cfg)],
                                      cwd=str(project), capture_output=True, text=True, encoding="utf-8", errors="replace",
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
        if not isinstance(data, dict) or data.get("status") != "completed" or data.get("stage") != "blockout":
            return {"status": "failed", "reason": "output_manifest_validation_failed", "project_dir": str(project)}
        return {"status": "completed", "task": "blender_mia_blockout", "stage": "blockout",
                "project_dir": str(project), "blend_path": str(blend), "preview_path": str(preview),
                "resolution": dimensions, "object_count": data.get("object_count"),
                "engine": data.get("engine"), "manual_review_required": True,
                "note": "Starter blockout only; not a finished or rigged production character."}

    completed = False
    try:
        result = generate()
        completed = result.get("status") == "completed"
        return result
    finally:
        if backup_dir is not None:
            if completed:
                shutil.rmtree(backup_dir, ignore_errors=True)
            else:
                # Preserve the backup if restoration itself fails, so recovery
                # never depends on a disposable TemporaryDirectory cleanup.
                try:
                    for path in existing:
                        if is_link_or_junction(path):
                            raise OSError("Output became a link during rendering")
                        shutil.copy2(backup_dir / path.name, path)
                except OSError as exc:
                    raise BlenderWorkflowError(f"Restore failed; previous files remain in {backup_dir}") from exc
                shutil.rmtree(backup_dir, ignore_errors=True)


def open_mia_project(project_name: str) -> dict[str, Any]:
    """Open an existing generated Mia project in Blender's GUI without UI clicks."""
    if not isinstance(project_name, str) or not _PROJECT_NAME.fullmatch(project_name):
        raise BlenderWorkflowError("Project name must contain only letters, digits, underscores, or hyphens.")
    blender = find_blender_executable()
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not workspace_value:
        return {"status": "blocked", "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally"}
    if blender is None:
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    workspace = Path(workspace_value).expanduser().resolve()
    project_dir = workspace / project_name
    if is_link_or_junction(project_dir):
        raise BlenderWorkflowError("Project folder must not be a symlink or junction.")
    project_dir = project_dir.resolve()
    if not project_dir.is_relative_to(workspace) or project_dir == workspace:
        raise BlenderWorkflowError("Project path must stay inside workspace.")
    blend = project_dir / "mia_blockout.blend"
    if not blender.is_file():
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    if is_link_or_junction(project_dir):
        raise BlenderWorkflowError("Project folder must not be a symlink or junction.")
    if blend.is_symlink() or not blend.is_file() or blend.stat().st_size == 0:
        return {"status": "blocked", "reason": "valid_mia_blockout_project_not_found", "project_dir": str(project_dir)}
    try:
        kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                                  "stderr": subprocess.DEVNULL, "close_fds": True}
        if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen([str(blender), "--disable-autoexec", str(blend)], cwd=str(project_dir),
                                   shell=False, **kwargs)
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}
    return {"status": "started", "project_path": str(blend),
            "process_id": getattr(process, "pid", None),
            "note": "Blender GUI launch requested; visual inspection is still required."}


def inspect_mia_project(project_name: str) -> dict[str, Any]:
    """Inspect a generated project with a bundled read-only Blender script."""
    if not isinstance(project_name, str) or not _PROJECT_NAME.fullmatch(project_name):
        raise BlenderWorkflowError("Project name must contain only letters, digits, underscores, or hyphens.")
    blender = find_blender_executable()
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not workspace_value:
        return {"status": "blocked", "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally"}
    if blender is None:
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    workspace = Path(workspace_value).expanduser().resolve()
    project_dir = workspace / project_name
    if is_link_or_junction(project_dir):
        raise BlenderWorkflowError("Project folder must not be a symlink or junction.")
    project_dir = project_dir.resolve()
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
            fresh_report = Path(temp) / "inspection.json"
            script.write_text(script_text, encoding="utf-8")
            proc = subprocess.run([str(blender), "--disable-autoexec", "--background",
                                   "--factory-startup", "--python-exit-code", "1",
                                   "--python", str(script), "--", str(blend), str(fresh_report)],
                                  cwd=str(project_dir), capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=180, check=False, shell=False)
            if proc.returncode != 0 or not fresh_report.is_file() or fresh_report.stat().st_size == 0:
                return {"status": "failed", "reason": "blender_inspection_failed",
                        "return_code": proc.returncode, "stderr_tail": (proc.stderr or "")[-2000:]}
            try:
                data = json.loads(fresh_report.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {"status": "failed", "reason": "inspection_report_unreadable"}
            if not isinstance(data, dict) or data.get("status") != "completed" or data.get("blend_path") != str(blend):
                return {"status": "failed", "reason": "inspection_report_validation_failed"}
            os.replace(fresh_report, report)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "blender_inspection_timeout"}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}
    return {"status": "completed", "task": "blender_inspect_mia_project", "inspection": data,
            "note": "Structural inspection only; it does not judge visual quality."}


# Fixed Spring donor preview implementation; deployed through the existing trusted update allowlist.

import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from local_agent.blender_locator import find_blender_executable
from local_agent.path_names import is_link_or_junction, path_identifier_pattern

SPRING_SHA256 = "8005f5cedb70faccd5557e6b0b001662f8681436f761d1f83e64feb9e02f0502"
SPRING_ATTRIBUTION = "Spring Rig (CC-BY) Blender Foundation | studio.blender.org"
_PROJECT_NAME = path_identifier_pattern(48)
_MAX_SCAN_DIRECTORIES = 50_000
_MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
_RENDER_TIMEOUT_SECONDS = 1200


class SpringPreviewError(RuntimeError):
    """A bounded Spring preview could not be produced safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_spring_donor(workspace: Path, *, expected_sha256: str = SPRING_SHA256) -> Path | None:
    """Find only the pinned Spring file beneath the configured local workspace."""
    root_value = Path(workspace).expanduser()
    if is_link_or_junction(root_value):
        raise SpringPreviewError("workspace_not_a_regular_directory")
    root = root_value.resolve()
    if not root.is_dir():
        raise SpringPreviewError("workspace_not_a_regular_directory")
    visited = 0
    matches: list[Path] = []
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        if is_link_or_junction(current):
            names[:] = []
            continue
        visited += 1
        if visited > _MAX_SCAN_DIRECTORIES:
            raise SpringPreviewError("workspace_scan_limit_exceeded")
        names[:] = [
            name for name in names
            if name.casefold() not in {".git", ".venv", "venv", "node_modules",
                                       "__pycache__", ".local_agent_worktrees"}
            and not is_link_or_junction(current / name)
        ]
        for filename in filenames:
            if filename.casefold() != "spring.blend":
                continue
            candidate = current / filename
            if is_link_or_junction(candidate) or not candidate.is_file():
                continue
            if candidate.stat().st_size > _MAX_SOURCE_BYTES:
                continue
            try:
                if _sha256(candidate).casefold() == expected_sha256.casefold():
                    matches.append(candidate.resolve())
            except OSError:
                continue
    if not matches:
        return None
    # Identical duplicates are harmless; deterministic selection aids review.
    return sorted(set(matches), key=lambda path: str(path).casefold())[0]


def _blender_script() -> str:
    """Return fixed Blender-side code; nothing from the mailbox is interpolated."""
    return r'''
import bpy, json, math, os, sys
from mathutils import Vector
args = sys.argv[sys.argv.index("--") + 1:]
with open(args[0], "r", encoding="utf-8") as stream:
    cfg = json.load(stream)
source = os.path.realpath(cfg["source"])
out = os.path.realpath(cfg["output_dir"])
bpy.ops.wm.open_mainfile(filepath=source)
scene = bpy.context.scene
rigs = [obj for obj in bpy.data.objects if obj.type == "ARMATURE" and obj.data.bones]
if not rigs:
    raise RuntimeError("Pinned Spring file contains no armature")
rig = max(rigs, key=lambda obj: len(obj.data.bones))
meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and not obj.hide_render]
if not meshes:
    raise RuntimeError("Pinned Spring file contains no visible mesh")
depsgraph = bpy.context.evaluated_depsgraph_get()
corners = []
for obj in meshes:
    evaluated = obj.evaluated_get(depsgraph)
    corners.extend(evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box)
if not corners:
    raise RuntimeError("Spring bounds are unavailable")
minimum = Vector((min(v.x for v in corners), min(v.y for v in corners), min(v.z for v in corners)))
maximum = Vector((max(v.x for v in corners), max(v.y for v in corners), max(v.z for v in corners)))
center = (minimum + maximum) * 0.5
height = max(maximum.z - minimum.z, 0.5)
width = max(maximum.x - minimum.x, 0.5)
# Remove cameras/lights only in the new output copy and provide deterministic framing.
for obj in list(bpy.context.scene.objects):
    if obj.type in {"CAMERA", "LIGHT"}:
        bpy.data.objects.remove(obj, do_unlink=True)
bpy.ops.object.camera_add(location=center + Vector((0, -max(height * 2.8, width * 1.6), height * 0.12)))
camera = bpy.context.object
camera.name = "Spring Preview Camera"
camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.lens = 50
scene.camera = camera
bpy.ops.object.light_add(type="AREA", location=center + Vector((-height, -height * 1.4, height * 1.7)))
key = bpy.context.object
key.name = "Spring Preview Key Light"
key.data.energy = 1400
key.data.shape = "DISK"
key.data.size = max(height, 2.0)
key.rotation_euler = (center - key.location).to_track_quat("-Z", "Y").to_euler()
bpy.ops.object.light_add(type="AREA", location=center + Vector((height, height, height * 0.8)))
fill = bpy.context.object
fill.name = "Spring Preview Fill Light"
fill.data.energy = 700
fill.data.size = max(height * 0.8, 1.0)
fill.rotation_euler = (center - fill.location).to_track_quat("-Z", "Y").to_euler()
world = scene.world or bpy.data.worlds.new("Spring Preview World")
scene.world = world
world.color = (0.12, 0.12, 0.12)
engine_ids = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
if "BLENDER_EEVEE_NEXT" in engine_ids:
    scene.render.engine = "BLENDER_EEVEE_NEXT"
elif "BLENDER_EEVEE" in engine_ids:
    scene.render.engine = "BLENDER_EEVEE"
else:
    raise RuntimeError("Eevee is unavailable")
scene.frame_start = 1
scene.frame_end = 60
scene.render.fps = 12
scene.render.resolution_x = 720
scene.render.resolution_y = 1280
scene.render.resolution_percentage = 100
scene.render.image_settings.color_mode = "RGB"
scene.render.film_transparent = False
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = os.path.join(out, "frame_")
scene.render.use_file_extension = True
scene.render.image_settings.color_mode = "RGB"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
scene.render.ffmpeg.audio_codec = "NONE"
scene.render.filepath = os.path.join(out, "spring_preview")
scene.render.image_settings.file_format = "FFMPEG"
# A gentle in-place turn and settle; the source model is never saved over.
rig.rotation_mode = "XYZ"
for frame, angle, lift in ((1, -0.14, 0.0), (30, 0.16, height * 0.025), (60, -0.14, 0.0)):
    rig.rotation_euler.z = angle
    rig.location.z = lift
    rig.keyframe_insert(data_path="rotation_euler", frame=frame, group="Spring preview")
    rig.keyframe_insert(data_path="location", frame=frame, group="Spring preview")
for action in bpy.data.actions:
    if action.name == "Spring preview":
        action.name = "Spring preview | gentle turn"
scene.frame_set(1)
blend_path = os.path.join(out, "spring_preview.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
bpy.ops.render.render(animation=True)
video_path = os.path.join(out, "spring_preview.mp4")
with open(os.path.join(out, "spring_preview_report.json"), "w", encoding="utf-8") as stream:
    json.dump({
        "status": "completed", "source_sha256": cfg["source_sha256"],
        "attribution": cfg["attribution"], "duration_seconds": 5,
        "fps": 12, "frames": 60, "resolution": [720, 1280],
        "silent": True, "blend_path": blend_path, "video_path": video_path,
        "action": "gentle_turn_and_settle", "rig_bones": len(rig.data.bones)
    }, stream, ensure_ascii=False, indent=2)
'''


def render_spring_preview(project_name: str) -> dict[str, Any]:
    """Render a silent, five-second portrait clip from the pinned local donor."""
    if not isinstance(project_name, str) or not _PROJECT_NAME.fullmatch(project_name):
        return {"status": "rejected", "reason": "invalid_project_name"}
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not workspace_value:
        return {"status": "blocked", "reason": "set_LOCAL_AGENT_WORKSPACE_locally"}
    blender = find_blender_executable()
    if blender is None or not blender.is_file():
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    workspace_value_path = Path(workspace_value).expanduser()
    if is_link_or_junction(workspace_value_path):
        return {"status": "blocked", "reason": "workspace_must_not_be_link_or_junction"}
    workspace = workspace_value_path.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    output = (workspace / project_name).resolve()
    if not output.is_relative_to(workspace) or is_link_or_junction(output):
        return {"status": "rejected", "reason": "unsafe_output_path"}
    if output.exists():
        return {"status": "blocked", "reason": "output_already_exists"}
    donor = find_spring_donor(workspace)
    if donor is None:
        return {"status": "blocked", "reason": "pinned_spring_donor_not_found"}
    output.mkdir()
    config = {
        "source": str(donor), "source_sha256": SPRING_SHA256,
        "attribution": SPRING_ATTRIBUTION, "output_dir": str(output),
    }
    config_path = output / "spring_preview_config.json"
    script_path = output / "spring_preview_runner.py"
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    script_path.write_text(_blender_script(), encoding="utf-8")
    stdout_path = output / "blender_stdout.log"
    stderr_path = output / "blender_stderr.log"
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            completed = subprocess.run(
                [str(blender.resolve()), "--background", "--disable-autoexec",
                 "--python", str(script_path), "--", str(config_path)],
                cwd=str(output), stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                timeout=_RENDER_TIMEOUT_SECONDS, check=False, shell=False,
            )
    except subprocess.TimeoutExpired:
        return {"status": "failed", "reason": "blender_render_timeout", "output_dir": str(output)}
    except OSError as exc:
        return {"status": "failed", "reason": "blender_launch_failed",
                "error_type": type(exc).__name__, "output_dir": str(output)}
    if completed.returncode != 0:
        return {"status": "failed", "reason": "blender_render_failed",
                "return_code": completed.returncode, "output_dir": str(output)}
    blend_path = output / "spring_preview.blend"
    video_path = output / "spring_preview.mp4"
    report_path = output / "spring_preview_report.json"
    expected = (blend_path, video_path, report_path)
    if any(is_link_or_junction(path) or not path.is_file() or path.stat().st_size == 0 for path in expected):
        return {"status": "failed", "reason": "expected_output_missing_or_invalid", "output_dir": str(output)}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {"status": "failed", "reason": "invalid_render_report", "output_dir": str(output)}
    if (report.get("source_sha256") != SPRING_SHA256 or report.get("duration_seconds") != 5
            or report.get("silent") is not True or report.get("frames") != 60):
        return {"status": "failed", "reason": "render_report_mismatch", "output_dir": str(output)}
    with video_path.open("rb") as stream:
        header = stream.read(12)
    if len(header) < 12 or header[4:8] != b"ftyp":
        return {"status": "failed", "reason": "invalid_mp4_container", "output_dir": str(output)}
    return {
        "status": "completed", "task": "blender_spring_preview",
        "duration_seconds": 5, "fps": 12, "resolution": [720, 1280],
        "silent": True, "blend_path": str(blend_path), "video_path": str(video_path),
        "source_sha256": SPRING_SHA256, "attribution": SPRING_ATTRIBUTION,
        "output_dir": str(output),
    }
