"""Safe local Blender launcher for deterministic starter-scene tasks.

The bridge accepts a small typed task schema; it never executes arbitrary Python
provided by a user or downloaded from the mailbox. Blender runs locally.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
from typing import Any, Callable

_PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
_ALLOWED_TASKS = {"forest_preview"}
_DEFAULT_TIMEOUT = 900


class BlenderBridgeError(RuntimeError):
    """A Blender launch or output-validation error."""


def _inside(root: Path, candidate: Path) -> Path:
    root = root.expanduser().resolve()
    candidate = candidate.expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise BlenderBridgeError("Output path must stay inside the configured workspace.")
    return resolved


def _write_bounded_log(path: Path, value: Any, max_bytes: int = 262_144) -> bool:
    """Keep a bounded local diagnostic tail without failing the render solely on logging."""
    try:
        if isinstance(value, bytes):
            raw = value
        else:
            raw = str(value or "").encode("utf-8", errors="replace")
        if len(raw) > max_bytes:
            raw = raw[-max_bytes:]
        path.write_text(raw.decode("utf-8", errors="replace"), encoding="utf-8")
        return True
    except OSError:
        return False


def _png_dimensions(path: Path) -> tuple[int, int]:
    """Read only the PNG signature and IHDR dimensions; reject empty/fake output."""
    try:
        with path.open("rb") as stream:
            header = stream.read(24)
    except OSError as exc:
        raise BlenderBridgeError("Preview PNG could not be read.") from exc
    if len(header) < 24 or header[:8] != b"\\x89PNG\\r\\n\\x1a\\n" or header[12:16] != b"IHDR":
        raise BlenderBridgeError("Preview output is not a valid PNG header.")
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        raise BlenderBridgeError("Preview PNG has invalid dimensions.")
    return width, height


def _scene_script() -> str:
    """Return a fixed script; all dynamic values are read as JSON data."""
    return r'''
import bpy, json, math, os, sys
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
with open(args[0], "r", encoding="utf-8") as handle:
    cfg = json.load(handle)
out_dir = os.path.realpath(cfg["output_dir"])
os.makedirs(out_dir, exist_ok=True)

# Start from a clean scene.
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
    pass

def material(name, color, roughness=0.82):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1.0)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
    return m

grass = material("Forest floor | moss", (0.16, 0.29, 0.13))
path_mat = material("Winding path | warm earth", (0.36, 0.25, 0.16))
bark = material("Tree bark", (0.22, 0.12, 0.07))
leaf_a = material("Canopy | deep green", (0.10, 0.27, 0.12))
leaf_b = material("Canopy | light green", (0.20, 0.39, 0.16))
sun_mat = material("Sun glow", (1.0, 0.73, 0.35))

bpy.ops.mesh.primitive_plane_add(size=70, location=(0, 0, -0.12))
ground = bpy.context.object
ground.name = "Forest floor"
ground.data.materials.append(grass)

# A broad, slightly winding path made from overlapping low-poly segments.
for i in range(12):
    y = -13 + i * 2.4
    x = math.sin(i * 0.43) * 1.8
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, -0.025))
    segment = bpy.context.object
    segment.name = "Path segment %02d" % i
    segment.dimensions = (3.8, 2.65, 0.12)
    segment.rotation_euler[2] = math.sin(i * 0.43) * 0.12
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    segment.data.materials.append(path_mat)
    bevel = segment.modifiers.new("Soft path edges", "BEVEL")
    bevel.width = 0.18
    bevel.segments = 2

# Deterministic procedural trees, kept outside the central path corridor.
for row in range(2):
    for i in range(11):
        y = -13 + i * 2.6 + (row * 0.7)
        side = -1 if row == 0 else 1
        x = side * (4.1 + (i % 3) * 1.05)
        height = 3.3 + (i % 4) * 0.48
        bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=0.22, depth=height * 0.48,
                                            location=(x, y, height * 0.24))
        trunk = bpy.context.object
        trunk.name = "Tree trunk %02d %02d" % (row, i)
        trunk.data.materials.append(bark)
        for layer in range(3):
            radius = 1.15 - layer * 0.23
            bpy.ops.mesh.primitive_cone_add(vertices=8, radius1=radius, radius2=0.06,
                                            depth=1.75, location=(x, y, height * 0.48 + layer * 0.82))
            crown = bpy.context.object
            crown.name = "Tree canopy %02d %02d %02d" % (row, i, layer)
            crown.data.materials.append(leaf_a if (i + layer) % 2 else leaf_b)

# Camera is framed as a vertical storybook establishing shot.
bpy.ops.object.camera_add(location=(10.8, -16.5, 9.4))
camera = bpy.context.object
camera.name = "Story camera | vertical"
target = Vector((0, 0, 1.0))
direction = target - camera.location
camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
camera.data.lens = 42
bpy.context.scene.camera = camera

bpy.ops.object.light_add(type="AREA", location=(-5, -2, 12))
key = bpy.context.object
key.name = "Soft forest sunlight"
key.data.energy = 1700
key.data.shape = "DISK"
key.data.size = 8
key.rotation_euler = (math.radians(25), 0, math.radians(-25))

bpy.ops.object.light_add(type="SUN", location=(4, 2, 9))
sun = bpy.context.object
sun.name = "Warm sun"
sun.data.energy = 1.6
sun.rotation_euler = (math.radians(25), math.radians(-18), math.radians(-25))

scene = bpy.context.scene
engine_ids = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
if cfg.get("cycles", False) and "CYCLES" in engine_ids:
    scene.render.engine = "CYCLES"
elif "BLENDER_EEVEE_NEXT" in engine_ids:
    scene.render.engine = "BLENDER_EEVEE_NEXT"
elif "BLENDER_EEVEE" in engine_ids:
    scene.render.engine = "BLENDER_EEVEE"
else:
    raise RuntimeError("No supported Eevee/Cycles render engine is available in this Blender build.")
scene.render.resolution_x = 720
scene.render.resolution_y = 1280
scene.render.resolution_percentage = 50 if cfg.get("preview", True) else 100
scene.render.film_transparent = False
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = os.path.join(out_dir, "forest_preview.png")
scene.world.color = (0.055, 0.055, 0.055)
scene.render.image_settings.color_mode = "RGBA"
scene.camera.data.lens = 42

blend_path = os.path.join(out_dir, "forest_starter.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
if cfg.get("render", True):
    bpy.ops.render.render(write_still=True)
with open(os.path.join(out_dir, "blender_result.json"), "w", encoding="utf-8") as handle:
    json.dump({"status": "completed", "blend_path": blend_path,
               "preview_path": scene.render.filepath if cfg.get("render", True) else None,
               "engine": scene.render.engine,
               "resolution": [scene.render.resolution_x, scene.render.resolution_y]}, handle, ensure_ascii=False)
'''


class BlenderBridge:
    """Launch a fixed, validated Blender task inside a user-selected workspace."""

    def __init__(
        self,
        blender_executable: str | os.PathLike[str],
        workspace: str | os.PathLike[str],
        *,
        timeout_seconds: int = _DEFAULT_TIMEOUT,
        popen: Callable[..., Any] = subprocess.run,
    ) -> None:
        executable = Path(blender_executable).expanduser().resolve()
        if not executable.is_file():
            raise BlenderBridgeError("Blender executable was not found; configure its full path.")
        self.executable = executable
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = max(30, min(int(timeout_seconds), 7200))
        self._run = popen

    def run_task(
        self,
        task: str,
        *,
        project_name: str,
        render: bool = True,
        preview: bool = True,
        cycles: bool = False,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        if not overwrite or not _PROJECT_NAME.fullmatch(project_name or ""):
            return self._run_task_impl(
                task, project_name=project_name, render=render, preview=preview,
                cycles=cycles, overwrite=overwrite,
            )

        requested = self.workspace / project_name
        if requested.is_symlink() or getattr(requested, "is_junction", lambda: False)():
            raise BlenderBridgeError("Project output directory must not be a symlink or junction.")
        project_dir = _inside(self.workspace, requested)
        if project_dir.exists() and not project_dir.is_dir():
            raise BlenderBridgeError("Project output path is not a directory.")
        if not project_dir.is_dir():
            return self._run_task_impl(
                task, project_name=project_name, render=render, preview=preview,
                cycles=cycles, overwrite=overwrite,
            )

        names = (
            "forest_starter.blend", "forest_preview.png", "blender_result.json",
            "blender_stdout.log", "blender_stderr.log",
        )
        known_outputs = [project_dir / name for name in names]
        if any(path.is_symlink() or getattr(path, "is_junction", lambda: False)() for path in known_outputs):
            raise BlenderBridgeError("Known output paths must not be symlinks or junctions.")
        existing = [path for path in known_outputs if path.exists()]
        if any(not path.is_file() for path in existing):
            raise BlenderBridgeError("Known output path exists but is not a regular file.")
        if not existing:
            return self._run_task_impl(
                task, project_name=project_name, render=render, preview=preview,
                cycles=cycles, overwrite=overwrite,
            )

        backup_dir = Path(tempfile.mkdtemp(prefix=".blender-backup-", dir=str(self.workspace)))
        moved: list[Path] = []
        log_names = {"blender_stdout.log", "blender_stderr.log"}
        try:
            for path in existing:
                os.replace(path, backup_dir / path.name)
                moved.append(path)
            result = self._run_task_impl(
                task, project_name=project_name, render=render, preview=preview,
                cycles=cycles, overwrite=True,
            )
        except BaseException as exc:
            restoration_errors: list[str] = []
            for path in moved:
                backup = backup_dir / path.name
                try:
                    if path.exists() or path.is_symlink():
                        if path.name in log_names and path.is_file() and not path.is_symlink():
                            # Keep the new failure log visible; the previous log
                            # remains in the retained backup directory.
                            continue
                        if path.is_dir() and not path.is_symlink():
                            raise OSError("new output path became a directory")
                        path.unlink(missing_ok=True)
                    if backup.is_file():
                        shutil.copy2(backup, path)
                except OSError as restore_exc:
                    restoration_errors.append(f"{path.name}: {type(restore_exc).__name__}")
            if restoration_errors:
                raise BlenderBridgeError(
                    "Blender failed and previous outputs could not all be restored; "
                    f"preserve and inspect backup directory {backup_dir}. "
                    f"Restore errors: {', '.join(restoration_errors)}"
                ) from exc
            if isinstance(exc, Exception):
                if hasattr(exc, "add_note"):
                    exc.add_note(
                        "Previous outputs were restored. The backup directory was retained "
                        f"for diagnosis: {backup_dir}"
                    )
                raise
            raise
        else:
            shutil.rmtree(backup_dir, ignore_errors=True)
            return result

    def _run_task_impl(
        self,
        task: str,
        *,
        project_name: str,
        render: bool = True,
        preview: bool = True,
        cycles: bool = False,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        if task not in _ALLOWED_TASKS:
            raise BlenderBridgeError("Unsupported Blender task. Allowed: forest_preview.")
        if not _PROJECT_NAME.fullmatch(project_name or ""):
            raise BlenderBridgeError("Project name must use 1-49 letters, digits, underscores, or hyphens.")
        requested_project_dir = self.workspace / project_name
        if requested_project_dir.is_symlink() or getattr(requested_project_dir, "is_junction", lambda: False)():
            raise BlenderBridgeError("Project output directory must not be a symlink or junction.")
        project_dir = _inside(self.workspace, requested_project_dir)
        project_dir.mkdir(parents=True, exist_ok=True)
        known_outputs = [
            project_dir / "forest_starter.blend",
            project_dir / "forest_preview.png",
            project_dir / "blender_result.json",
            project_dir / "blender_stdout.log",
            project_dir / "blender_stderr.log",
        ]
        if any(path.is_symlink() or getattr(path, "is_junction", lambda: False)() for path in known_outputs):
            raise BlenderBridgeError("Known output paths must not be symlinks or junctions.")
        if not overwrite and any(path.exists() for path in known_outputs):
            raise BlenderBridgeError(
                "This project already has generated outputs; use overwrite=True only when intentional."
            )
        if overwrite:
            for path in known_outputs:
                if path.exists():
                    if not path.is_file():
                        raise BlenderBridgeError("Known output path exists but is not a regular file.")
                    path.unlink()
        config = {
            "output_dir": str(project_dir),
            "render": bool(render),
            "preview": bool(preview),
            "cycles": bool(cycles),
        }
        # Keep generated runner/config within the project workspace and never accept
        # executable script content from a mailbox or a natural-language prompt.
        with tempfile.TemporaryDirectory(prefix=".blender-task-", dir=project_dir) as temp:
            temp_dir = Path(temp)
            script_path = temp_dir / "starter_scene.py"
            config_path = temp_dir / "task.json"
            script_path.write_text(_scene_script(), encoding="utf-8")
            config_path.write_text(json.dumps(config), encoding="utf-8")
            command = [
                str(self.executable), "--background", "--factory-startup",
                "--python", str(script_path), "--", str(config_path),
            ]
            try:
                result = self._run(
                    command, cwd=str(project_dir), capture_output=True, text=True,
                    timeout=self.timeout_seconds, check=False,
                )
            except subprocess.TimeoutExpired as exc:
                _write_bounded_log(project_dir / "blender_stdout.log", exc.stdout)
                _write_bounded_log(project_dir / "blender_stderr.log", exc.stderr)
                raise BlenderBridgeError("Blender task timed out; bounded local logs were saved when possible.") from exc
            except OSError as exc:
                raise BlenderBridgeError(f"Could not launch Blender ({type(exc).__name__}).") from exc
            stdout_logged = _write_bounded_log(project_dir / "blender_stdout.log", result.stdout)
            stderr_logged = _write_bounded_log(project_dir / "blender_stderr.log", result.stderr)
            if result.returncode != 0:
                stderr = (result.stderr or "")[-3000:]
                raise BlenderBridgeError(
                    f"Blender exited with code {result.returncode}; "
                    f"local_logs_written={stdout_logged and stderr_logged}: {stderr}"
                )
        result_path = project_dir / "blender_result.json"
        if result_path.is_symlink() or getattr(result_path, "is_junction", lambda: False)():
            raise BlenderBridgeError("Blender result manifest must not be a symlink or junction.")
        if not result_path.is_file() or result_path.stat().st_size == 0:
            raise BlenderBridgeError("Blender exited without writing its result manifest.")
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BlenderBridgeError("Blender result manifest is unreadable.") from exc
        expected_blend = _inside(project_dir, project_dir / "forest_starter.blend")
        if (payload.get("status") != "completed" or not expected_blend.is_file()
                or expected_blend.is_symlink() or expected_blend.stat().st_size == 0):
            raise BlenderBridgeError("Blender result manifest failed validation.")
        if payload.get("blend_path") != str(expected_blend):
            raise BlenderBridgeError("Blender result manifest points to an unexpected project file.")
        if payload.get("resolution") != [720, 1280]:
            raise BlenderBridgeError("Blender result manifest has unexpected base resolution.")
        if payload.get("engine") not in {"BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"}:
            raise BlenderBridgeError("Blender result manifest has an unsupported render engine.")
        if render:
            expected_preview = _inside(project_dir, project_dir / "forest_preview.png")
            if (not expected_preview.is_file() or expected_preview.is_symlink()
                    or expected_preview.stat().st_size == 0):
                raise BlenderBridgeError("Expected preview render is missing or empty.")
            if payload.get("preview_path") != str(expected_preview):
                raise BlenderBridgeError("Blender result manifest points to an unexpected preview file.")
            expected_size = (720 if not preview else 360, 1280 if not preview else 640)
            if _png_dimensions(expected_preview) != expected_size:
                raise BlenderBridgeError("Preview render dimensions do not match the requested resolution.")
        elif payload.get("preview_path") is not None:
            raise BlenderBridgeError("Blender reported a preview path even though rendering was disabled.")
        return payload
