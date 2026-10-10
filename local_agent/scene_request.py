"""Safe Russian-language request parser and GUI executor for simple Blender scenes.

Natural language is converted into a bounded JSON scene plan. The user's prompt
is never treated as Python, shell syntax, an expression, or a file path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time
from typing import Any

_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
_MAX_PROMPT_CHARS = 1200
_MAX_OBJECTS = 40
_DEFAULT_TIMEOUT = 900

_PRIMITIVES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cube", ("куб", "куба", "кубом", "кубе", "кубы", "кубами", "кубик", "кубики", "кубов")),
    ("uv_sphere", ("сфера", "сферу", "сферы", "сфер", "сферой", "шара", "шар", "шары", "шаром", "шарами")),
    ("cylinder", ("цилиндр", "цилиндра", "цилиндры")),
    ("cone", ("конус", "конуса", "конусы")),
    ("torus", ("тор", "кольцо", "кольца", "кольцо")),
    ("monkey", ("обезьяна", "голова обезьяны", "мэш")),
)
_COLORS: tuple[tuple[str, tuple[str, ...], tuple[float, float, float, float]], ...] = (
    ("red", ("красный", "красная", "красное", "красные", "красного", "красную", "красных"), (0.8, 0.035, 0.025, 1.0)),
    ("green", ("зелёный", "зеленый", "зелёная", "зеленая", "зелёное", "зелёные", "зеленые", "зелёных", "зеленых"), (0.04, 0.48, 0.12, 1.0)),
    ("blue", ("синий", "синяя", "синее", "синие", "синих", "голубой", "голубая"), (0.025, 0.18, 0.85, 1.0)),
    ("yellow", ("жёлтый", "желтый", "жёлтая", "желтая", "жёлтое", "желтое", "жёлтых", "желтых"), (0.95, 0.58, 0.025, 1.0)),
    ("orange", ("оранжевый", "оранжевая", "оранжевое"), (1.0, 0.22, 0.025, 1.0)),
    ("purple", ("фиолетовый", "фиолетовая", "фиолетовое"), (0.38, 0.07, 0.68, 1.0)),
    ("white", ("белый", "белая", "белое", "белые"), (0.88, 0.88, 0.88, 1.0)),
    ("black", ("чёрный", "черный", "чёрная", "черная", "чёрное", "черное"), (0.025, 0.025, 0.025, 1.0)),
    ("brown", ("коричневый", "коричневая", "коричневое"), (0.28, 0.11, 0.035, 1.0)),
    ("pink", ("розовый", "розовая", "розовое"), (0.95, 0.12, 0.42, 1.0)),
    ("gray", ("серый", "серая", "серое", "серые"), (0.32, 0.35, 0.38, 1.0)),
)
_COLOR_DEFAULT = (0.22, 0.42, 0.68, 1.0)
_COUNT_WORDS = {
    "один": 1, "одна": 1, "одно": 1, "два": 2, "две": 2, "три": 3,
    "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8,
    "девять": 9, "десять": 10,
}
_COUNT_TOKEN = r"(?:\d{1,2}|" + "|".join(_COUNT_WORDS) + r")"
_LOCAL_COUNT = re.compile(r"(?<![а-яё\w])(" + _COUNT_TOKEN + r")(?![а-яё\w])(?:\s+[а-яё-]+){0,3}\s*$")
_SIZE = re.compile(r"(?:размер(?:ом)?|масштаб(?:ом)?)\s*(?:=\s*)?(\d+(?:[.,]\d+)?)")

class SceneRequestError(ValueError):
    """A natural-language scene request is unsupported or unsafe."""


def parse_scene_request(prompt: str) -> dict[str, Any]:
    """Compile a small Russian request into an inert, bounded scene plan."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > _MAX_PROMPT_CHARS:
        raise SceneRequestError(f"Prompt must contain 1-{_MAX_PROMPT_CHARS} characters.")
    text = prompt.casefold()
    matches: list[tuple[int, str, str, int]] = []
    for primitive, aliases in _PRIMITIVES:
        for alias in aliases:
            for found in re.finditer(r"(?<![а-яё])" + re.escape(alias) + r"(?![а-яё])", text):
                matches.append((found.start(), primitive, alias, found.end()))
    matches.sort(key=lambda item: (item[0], -(item[3] - item[0])))
    # Keep only the longest non-overlapping primitive match at each position.
    selected: list[tuple[int, str, str, int]] = []
    for item in matches:
        if selected and item[0] < selected[-1][3]:
            continue
        selected.append(item)
    if not selected:
        raise SceneRequestError(
            "Не удалось распознать объект. Поддерживаются куб, сфера/шар, цилиндр, конус, тор и обезьяна (Suzanne)."
        )

    # Mask aspect ratios without changing offsets, so 9:16 is never an object count.
    count_text = re.sub(r"\d+\s*:\s*\d+", lambda match: " " * len(match.group(0)), text)
    count_text = _SIZE.sub(lambda match: " " * len(match.group(0)), count_text)
    global_count = None
    leading_count = re.match(r"^\s*(" + _COUNT_TOKEN + r")\b", count_text)
    if leading_count:
        token = leading_count.group(1)
        value = int(token) if token.isdigit() else _COUNT_WORDS[token]
        if 1 <= value <= _MAX_OBJECTS:
            global_count = value
    size = 1.0
    size_match = _SIZE.search(text)
    if size_match:
        try:
            size = float(size_match.group(1).replace(",", "."))
        except ValueError as exc:
            raise SceneRequestError("Некорректный размер объекта.") from exc
    elif "больш" in text:
        size = 1.8
    elif "малень" in text:
        size = 0.55
    if not 0.1 <= size <= 10:
        raise SceneRequestError("Размер должен быть от 0.1 до 10.")

    color_name, color = "blue", _COLOR_DEFAULT
    for candidate, aliases, rgba in _COLORS:
        if any(re.search(r"(?<![а-яё])" + re.escape(alias) + r"(?![а-яё])", text) for alias in aliases):
            color_name, color = candidate, rgba
            break

    objects: list[dict[str, Any]] = []
    previous_end = 0
    for pos, primitive, alias, end in selected:
        # Match a count immediately before the primitive, allowing up to three adjectives.
        prefix = count_text[max(previous_end, pos - 64):pos]
        local_count = _LOCAL_COUNT.search(prefix)
        count = 1
        if local_count:
            token = local_count.group(1)
            candidate_count = int(token) if token.isdigit() else _COUNT_WORDS[token]
            if 1 <= candidate_count <= _MAX_OBJECTS:
                count = candidate_count
        elif not objects and global_count is not None:
            count = global_count
        if len(objects) + count > _MAX_OBJECTS:
            raise SceneRequestError(f"Scene is limited to {_MAX_OBJECTS} objects.")
        color_segment = text[previous_end:pos]
        object_color_name, object_color = color_name, color
        for candidate, aliases, rgba in _COLORS:
            if any(re.search(r"(?<![а-яё])" + re.escape(word) + r"(?![а-яё])", color_segment) for word in aliases):
                object_color_name, object_color = candidate, rgba
        for _ in range(count):
            objects.append({
                "primitive": primitive,
                "color_name": object_color_name,
                "color": list(object_color),
                "scale": size,
                "name": f"{primitive.replace('_', ' ').title()} {len(objects) + 1:02d}",
            })
        previous_end = end

    if "9:16" in text or "вертикаль" in text or "портрет" in text:
        resolution = [720, 1280]
        aspect = "9:16"
    elif "1:1" in text or "квадрат" in text:
        resolution = [1024, 1024]
        aspect = "1:1"
    else:
        resolution = [1280, 720]
        aspect = "16:9"
    return {
        "schema_version": 1,
        "objects": objects,
        "resolution": resolution,
        "aspect_ratio": aspect,
        "render_percentage": 50,
        "prompt_summary": prompt.strip(),
    }


_BLENDER_SCRIPT = r'''
import bpy, json, math, os, sys
from mathutils import Vector
args = sys.argv[sys.argv.index("--") + 1:]
with open(args[0], "r", encoding="utf-8") as stream:
    cfg = json.load(stream)
out_dir = os.path.realpath(cfg["output_dir"])
os.makedirs(out_dir, exist_ok=True)
scene = bpy.context.scene
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

def make_material(index, rgba):
    material = bpy.data.materials.new("Agent material %02d" % index)
    material.diffuse_color = tuple(rgba)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = tuple(rgba)
        bsdf.inputs["Roughness"].default_value = 0.42
    return material

for index, item in enumerate(cfg["objects"]):
    primitive = item["primitive"]
    location = ((index - (len(cfg["objects"]) - 1) / 2) * 2.3, 0.0, 1.0)
    if primitive == "cube":
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    elif primitive == "uv_sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=20, location=location)
        for polygon in bpy.context.object.data.polygons: polygon.use_smooth = True
    elif primitive == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.65, depth=1.5, location=location)
    elif primitive == "cone":
        bpy.ops.mesh.primitive_cone_add(vertices=32, radius1=0.7, radius2=0.0, depth=1.5, location=location)
    elif primitive == "torus":
        bpy.ops.mesh.primitive_torus_add(major_segments=48, minor_segments=16, location=location)
    elif primitive == "monkey":
        bpy.ops.mesh.primitive_monkey_add(location=location)
    else:
        raise RuntimeError("Unsupported primitive in validated plan.")
    obj = bpy.context.object
    obj.name = item["name"]
    obj.scale = (item["scale"],) * 3
    obj.data.materials.append(make_material(index + 1, item["color"]))

# Neutral floor and lighting make the first render useful without external assets.
floor_material = make_material(99, (0.12, 0.14, 0.17, 1.0))
bpy.ops.mesh.primitive_plane_add(size=max(18.0, len(cfg["objects"]) * 3.0), location=(0, 0, -0.02))
bpy.context.object.name = "Environment | floor"
bpy.context.object.data.materials.append(floor_material)

center_x = 0.0
bpy.ops.object.camera_add(location=(center_x + 7.0, -10.0, 7.5))
camera = bpy.context.object
camera.name = "Camera | generated scene"
target = Vector((0.0, 0.0, 0.8))
camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.lens = 50
scene.camera = camera

bpy.ops.object.light_add(type="AREA", location=(-4.0, -4.0, 8.0))
key = bpy.context.object
key.name = "Light | key"
key.data.energy = 1250
key.data.shape = "DISK"
key.data.size = 6
key.rotation_euler = (Vector((0, 0, 0.5)) - key.location).to_track_quat("-Z", "Y").to_euler()
bpy.ops.object.light_add(type="AREA", location=(5.0, 3.0, 5.0))
fill = bpy.context.object
fill.name = "Light | fill"
fill.data.energy = 650
fill.data.size = 5
fill.rotation_euler = (Vector((0, 0, 0.5)) - fill.location).to_track_quat("-Z", "Y").to_euler()

engine_ids = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
if "BLENDER_EEVEE_NEXT" in engine_ids:
    scene.render.engine = "BLENDER_EEVEE_NEXT"
elif "BLENDER_EEVEE" in engine_ids:
    scene.render.engine = "BLENDER_EEVEE"
else:
    raise RuntimeError("No supported Eevee engine found.")
scene.render.resolution_x, scene.render.resolution_y = cfg["resolution"]
scene.render.resolution_percentage = cfg["render_percentage"]
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.filepath = os.path.join(out_dir, "scene_preview.png")
scene.world.color = (0.055, 0.055, 0.055)
blend_path = os.path.join(out_dir, "scene.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
bpy.ops.render.render(write_still=True)
with open(os.path.join(out_dir, "scene_result.json"), "w", encoding="utf-8") as stream:
    json.dump({
        "status": "completed",
        "blend_path": blend_path,
        "preview_path": scene.render.filepath,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "engine": scene.render.engine,
        "object_count": len(scene.objects),
        "generated_object_count": len(cfg["objects"]),
        "aspect_ratio": cfg["aspect_ratio"],
    }, stream, ensure_ascii=False)
'''


def create_scene_from_prompt(prompt: str, project_name: str, *, timeout_seconds: int = _DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Create a simple scene in the visible Blender GUI from a bounded Russian prompt."""
    plan = parse_scene_request(prompt)
    if not isinstance(project_name, str) or not _PROJECT_RE.fullmatch(project_name):
        raise SceneRequestError("Project name must use 1-48 letters, digits, underscores, or hyphens.")
    blender_value = os.environ.get("BLENDER_EXECUTABLE", "").strip()
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not blender_value or not workspace_value:
        return {"status": "blocked", "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally"}
    blender = Path(blender_value).expanduser().resolve()
    workspace = Path(workspace_value).expanduser().resolve()
    if not blender.is_file():
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    workspace.mkdir(parents=True, exist_ok=True)
    if workspace.is_symlink() or getattr(workspace, "is_junction", lambda: False)():
        raise SceneRequestError("Workspace must not be a symlink or junction.")
    project = workspace / project_name
    if project.is_symlink() or getattr(project, "is_junction", lambda: False)():
        raise SceneRequestError("Project directory must not be a symlink or junction.")
    project.mkdir(parents=True, exist_ok=True)
    project = project.resolve()
    if not project.is_relative_to(workspace) or project == workspace:
        raise SceneRequestError("Project must stay inside the workspace.")
    outputs = [project / "scene.blend", project / "scene_preview.png", project / "scene_result.json",
               project / "blender_stdout.log", project / "blender_stderr.log"]
    if any(path.is_symlink() or getattr(path, "is_junction", lambda: False)() for path in outputs):
        raise SceneRequestError("Output paths must not be symlinks or junctions.")
    if any(path.exists() for path in outputs):
        raise SceneRequestError("Scene outputs already exist; choose a new project name to preserve existing files.")
    cfg = dict(plan)
    cfg["output_dir"] = str(project)
    timeout = max(30, min(int(timeout_seconds), 7200))
    with tempfile.TemporaryDirectory(prefix=".scene-request-", dir=project) as temp:
        script_path = Path(temp) / "scene_builder.py"
        config_path = Path(temp) / "scene_plan.json"
        script_path.write_text(_BLENDER_SCRIPT, encoding="utf-8")
        config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        stdout_path, stderr_path = outputs[-2], outputs[-1]
        result_path = outputs[2]
        with stdout_path.open("wb") as stdout_stream, stderr_path.open("wb") as stderr_stream:
            try:
                process = subprocess.Popen(
                    [str(blender), "--disable-autoexec", "--factory-startup", "--python",
                     str(script_path), "--", str(config_path)],
                    cwd=str(project), stdin=subprocess.DEVNULL, stdout=stdout_stream,
                    stderr=stderr_stream, shell=False, close_fds=True,
                )
            except OSError as exc:
                raise SceneRequestError(f"Blender could not be started ({type(exc).__name__}).") from exc
            deadline = time.monotonic() + timeout
            while True:
                if result_path.is_file() and result_path.stat().st_size > 0:
                    try:
                        manifest = json.loads(result_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        manifest = {}
                    if manifest.get("status") == "completed":
                        break
                code = process.poll()
                if code is not None:
                    tail = ""
                    try:
                        tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-3000:]
                    except OSError:
                        pass
                    raise SceneRequestError(f"Blender exited before completing the scene (code {code}). {tail}")
                if time.monotonic() >= deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise SceneRequestError(f"Blender scene creation timed out after {timeout} seconds.")
                time.sleep(0.25)

    blend = project / "scene.blend"
    preview = project / "scene_preview.png"
    if not blend.is_file() or blend.stat().st_size == 0 or not preview.is_file() or preview.stat().st_size < 24:
        raise SceneRequestError("Blender reported completion but the project or preview is missing.")
    with preview.open("rb") as stream:
        header = stream.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise SceneRequestError("Preview output is not a valid PNG.")
    dimensions = list(struct.unpack(">II", header[16:24]))
    expected = [max(1, int(x * plan["render_percentage"] / 100)) for x in plan["resolution"]]
    if dimensions != expected:
        raise SceneRequestError(f"Preview dimensions mismatch: expected {expected}, got {dimensions}.")
    manifest = json.loads((project / "scene_result.json").read_text(encoding="utf-8"))
    if manifest.get("blend_path") != str(blend) or manifest.get("preview_path") != str(preview):
        raise SceneRequestError("Blender result manifest points to an unexpected path.")
    manifest["project_name"] = project_name
    manifest["prompt_summary"] = prompt.strip()
    manifest["preview_dimensions"] = dimensions
    return manifest
