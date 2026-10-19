"""Fixed, fail-closed five-second preview of the Blender Foundation Spring donor.

The mailbox accepts only a project identifier. The source is discovered locally
and must match the pinned CC-BY donor SHA-256; no remote path or Python is accepted.
"""
from __future__ import annotations

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
