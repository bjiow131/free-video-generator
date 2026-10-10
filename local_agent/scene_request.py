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
    ("yellow", ("жёлтый", "желтый", "жёлтая", "желтая", "жёлтое", "желтое", "жёлтых", "желтых", "жёлтым", "желтым"), (0.95, 0.58, 0.025, 1.0)),
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
    """Compatibility wrapper around the expanded, inert natural-language compiler."""
    from local_agent.scene_language import SceneRequestError as PlannerError, parse_scene_request as compile_prompt
    try:
        return compile_prompt(prompt)
    except PlannerError as exc:
        raise SceneRequestError(str(exc)) from exc


_BLENDER_SCRIPT = r'''
import bpy, json, math, os, sys, traceback
from mathutils import Vector
args = sys.argv[sys.argv.index("--") + 1:]
with open(args[0], "r", encoding="utf-8") as stream:
    cfg = json.load(stream)
def _agent_excepthook(exc_type, exc, tb):
    try:
        with open(os.path.join(cfg["output_dir"], "scene_result.json"), "w", encoding="utf-8") as stream:
            json.dump({"status": "failed", "error": str(exc), "error_type": getattr(exc_type, "__name__", "Exception")}, stream, ensure_ascii=False)
    except Exception:
        pass
    traceback.print_exception(exc_type, exc, tb)
sys.excepthook = _agent_excepthook
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

def material_for(name, rgba, roughness=0.48, metallic=0.0):
    key = "Agent | " + name
    material = bpy.data.materials.get(key) or bpy.data.materials.new(key)
    material.diffuse_color = tuple(rgba)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = tuple(rgba)
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
    return material

def add_prim(kind, location, scale, mat, name):
    if kind == "cube":
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    elif kind == "uv_sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=20, location=location)
        for polygon in bpy.context.object.data.polygons: polygon.use_smooth = True
    elif kind == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.5, depth=1.0, location=location)
    elif kind == "cone":
        bpy.ops.mesh.primitive_cone_add(vertices=32, radius1=0.7, radius2=0.0, depth=1.0, location=location)
    elif kind == "torus":
        bpy.ops.mesh.primitive_torus_add(major_segments=48, minor_segments=16, location=location)
    elif kind == "monkey":
        bpy.ops.mesh.primitive_monkey_add(location=location)
    elif kind == "rock":
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1.0, location=location)
    else:
        raise RuntimeError("Unsupported primitive: " + str(kind))
    obj = bpy.context.object
    obj.name = name
    obj.scale = (scale[0], scale[1], scale[2])
    if mat: obj.data.materials.append(mat)
    if kind in ("uv_sphere", "cylinder", "cone", "torus"): 
        for polygon in obj.data.polygons: polygon.use_smooth = kind == "uv_sphere"
    return obj

def make_item(item, location, index):
    kind = item["primitive"]
    s = max(0.1, float(item["scale"]))
    base = Vector(location)
    color = item["color"]
    primary = material_for(item["color_name"], color)
    wood = material_for("wood", (0.28, 0.105, 0.035, 1.0))
    leaf = material_for("foliage", (0.055, 0.31, 0.09, 1.0))
    roof = material_for("roof", (0.35, 0.055, 0.035, 1.0))
    glass = material_for("glass", (0.08, 0.48, 0.72, 1.0), 0.22, 0.15)
    dark = material_for("dark metal", (0.025, 0.035, 0.045, 1.0), 0.32, 0.45)
    made = []
    def part(k, off, sc, mat, suffix):
        obj = add_prim(k, tuple(base + Vector(off) * s), tuple(float(v) * s for v in sc), mat, item["name"] + " | " + suffix)
        made.append(obj)
        return obj
    if kind in ("cube", "uv_sphere", "cylinder", "cone", "torus", "monkey", "rock"):
        obj = add_prim(kind, location, (s, s, s), primary, item["name"])
        made.append(obj)
    elif kind == "tree":
        part("cylinder", (0, 0, 0.72), (0.20, 0.20, 0.85), wood, "trunk")
        part("cone", (0, 0, 1.45), (0.95, 0.95, 0.90), leaf, "crown lower")
        part("cone", (0, 0, 2.00), (0.70, 0.70, 0.78), leaf, "crown middle")
        part("cone", (0, 0, 2.48), (0.45, 0.45, 0.65), leaf, "crown top")
    elif kind == "house":
        part("cube", (0, 0, 0.65), (1.55, 1.30, 1.30), primary, "walls")
        part("cone", (0, 0, 1.65), (1.25, 1.25, 0.85), roof, "roof")
        part("cube", (0, -0.665, 0.34), (0.34, 0.08, 0.66), wood, "door")
        part("cube", (-0.48, -0.67, 0.88), (0.30, 0.07, 0.28), glass, "window left")
        part("cube", (0.48, -0.67, 0.88), (0.30, 0.07, 0.28), glass, "window right")
    elif kind == "mountain":
        part("cone", (0, 0, 1.0), (1.8, 1.5, 2.2), primary, "peak")
        part("cone", (0.2, -0.35, 1.85), (0.58, 0.50, 0.62), material_for("snow", (0.88, 0.92, 0.96, 1)), "snow cap")
    elif kind == "cloud":
        part("uv_sphere", (-0.55, 0, 0), (0.68, 0.52, 0.50), primary, "left puff")
        part("uv_sphere", (0, 0.05, 0.20), (0.78, 0.62, 0.64), primary, "center puff")
        part("uv_sphere", (0.58, 0, 0), (0.62, 0.50, 0.45), primary, "right puff")
    elif kind == "person":
        part("uv_sphere", (0, 0, 1.68), (0.30, 0.30, 0.30), material_for("skin", (0.72, 0.45, 0.30, 1)), "head")
        part("cylinder", (0, 0, 1.05), (0.30, 0.25, 0.55), primary, "torso")
        part("cylinder", (-0.38, 0, 1.05), (0.10, 0.10, 0.45), primary, "left arm")
        part("cylinder", (0.38, 0, 1.05), (0.10, 0.10, 0.45), primary, "right arm")
        part("cylinder", (-0.16, 0, 0.38), (0.12, 0.12, 0.42), dark, "left leg")
        part("cylinder", (0.16, 0, 0.38), (0.12, 0.12, 0.42), dark, "right leg")
    elif kind == "car":
        part("cube", (0, 0, 0.48), (1.85, 0.88, 0.48), primary, "body")
        part("cube", (0.08, 0, 0.83), (0.90, 0.72, 0.42), glass, "cabin")
        for x in (-0.62, 0.62):
            for y in (-0.48, 0.48):
                part("cylinder", (x, y, 0.24), (0.22, 0.22, 0.12), dark, "wheel")
    elif kind == "table":
        part("cube", (0, 0, 0.88), (1.55, 1.05, 0.16), primary, "top")
        for x in (-0.62, 0.62):
            for y in (-0.38, 0.38): part("cube", (x, y, 0.42), (0.12, 0.12, 0.82), wood, "leg")
    elif kind == "chair":
        part("cube", (0, 0, 0.55), (0.85, 0.80, 0.14), primary, "seat")
        part("cube", (0, 0.34, 1.02), (0.85, 0.12, 0.90), wood, "back")
        for x in (-0.32, 0.32):
            for y in (-0.28, 0.28): part("cube", (x, y, 0.27), (0.10, 0.10, 0.52), wood, "leg")
    elif kind == "lamp":
        part("cylinder", (0, 0, 0.78), (0.10, 0.10, 1.5), dark, "stand")
        part("cylinder", (0, 0, 1.58), (0.48, 0.48, 0.22), primary, "shade")
        part("uv_sphere", (0, 0, 1.43), (0.16, 0.16, 0.16), material_for("lamp glow", (1.0, 0.75, 0.32, 1)), "bulb")
    elif kind == "bench":
        part("cube", (0, 0, 0.58), (1.65, 0.50, 0.12), wood, "seat")
        part("cube", (0, 0.20, 0.92), (1.65, 0.10, 0.62), primary, "back")
        for x in (-0.62, 0.62): part("cube", (x, 0, 0.28), (0.10, 0.12, 0.55), dark, "leg")
    elif kind == "flower":
        part("cylinder", (0, 0, 0.48), (0.06, 0.06, 0.92), leaf, "stem")
        for j in range(5):
            a = j * math.tau / 5
            part("uv_sphere", (math.cos(a)*0.22, math.sin(a)*0.22, 1.0), (0.18, 0.18, 0.15), primary, "petal")
        part("uv_sphere", (0, 0, 1.0), (0.13, 0.13, 0.13), material_for("flower center", (0.98, 0.66, 0.04, 1)), "center")
    elif kind == "grass":
        for j in range(5):
            a = j * math.tau / 5
            part("cone", (math.cos(a)*0.14, math.sin(a)*0.14, 0.32), (0.13, 0.13, 0.62), leaf, "blade")
    elif kind == "road":
        part("cube", (0, 0, 0.04), (2.2, 0.18, 0.08), dark, "road")
        for x in (-0.7, 0, 0.7): part("cube", (x, 0, 0.09), (0.25, 0.025, 0.015), material_for("road marking", (0.95,0.88,0.62,1)), "marking")
    elif kind == "fence":
        for x in (-0.75, -0.25, 0.25, 0.75): part("cube", (x, 0, 0.40), (0.07, 0.12, 0.80), wood, "post")
        for z in (0.25, 0.58): part("cube", (0, 0, z), (1.65, 0.10, 0.08), primary, "rail")
    elif kind == "bed":
        part("cube", (0, 0, 0.40), (1.9, 1.1, 0.35), wood, "frame")
        part("cube", (0, 0, 0.63), (1.82, 1.02, 0.18), primary, "mattress")
        part("cube", (-0.55, 0.28, 0.78), (0.42, 0.36, 0.10), material_for("pillow", (0.92,0.90,0.82,1)), "pillow")
    elif kind == "book":
        part("cube", (0, 0, 0.10), (0.95, 0.68, 0.18), primary, "cover")
        part("cube", (0, -0.01, 0.20), (0.86, 0.62, 0.035), material_for("paper", (0.91,0.86,0.72,1)), "pages")
    elif kind == "mug":
        part("cylinder", (0, 0, 0.35), (0.48, 0.48, 0.68), primary, "cup")
        part("torus", (0.48, 0, 0.38), (0.24, 0.24, 0.08), primary, "handle")
    elif kind == "bottle":
        part("cylinder", (0, 0, 0.45), (0.38, 0.38, 0.82), primary, "body")
        part("cylinder", (0, 0, 0.98), (0.16, 0.16, 0.30), primary, "neck")
        part("cylinder", (0, 0, 1.15), (0.18, 0.18, 0.08), dark, "cap")
    elif kind == "smartphone":
        part("cube", (0, 0, 0.08), (0.55, 0.08, 1.05), dark, "body")
        part("cube", (0, -0.05, 0.08), (0.47, 0.018, 0.88), glass, "screen")
    elif kind == "rocket":
        part("cylinder", (0, 0, 0.60), (0.38, 0.38, 1.35), primary, "body")
        part("cone", (0, 0, 1.45), (0.38, 0.38, 0.55), roof, "nose")
        for x in (-0.32, 0.32): part("cone", (x, 0, 0.12), (0.20, 0.20, 0.55), roof, "fin")
    elif kind == "mia":
        skin = material_for("Mia | skin", (0.78, 0.53, 0.39, 1))
        hair = material_for("Mia | muted brown hair", (0.24, 0.105, 0.045, 1))
        shirt = material_for("Mia | white shirt", (0.94, 0.93, 0.88, 1))
        overalls = material_for("Mia | turquoise overalls", (0.025, 0.56, 0.56, 1))
        yellow = material_for("Mia | yellow details", (1.0, 0.72, 0.035, 1))
        eyes = material_for("Mia | eye whites", (1.0, 0.98, 0.90, 1))
        pupils = material_for("Mia | pupils", (0.025, 0.018, 0.014, 1))
        pink = material_for("Mia | pink backpack", (1.0, 0.13, 0.48, 1))
        part("uv_sphere", (0, -0.015, 1.72), (0.39, 0.34, 0.40), skin, "large head")
        part("uv_sphere", (0, 0.035, 1.98), (0.41, 0.34, 0.24), hair, "hair cap")
        for x in (-0.31, 0.31):
            part("uv_sphere", (x, 0.045, 1.68), (0.13, 0.18, 0.34), hair, "shoulder hair")
        for x in (-0.24, 0.24):
            part("uv_sphere", (x, -0.335, 1.76), (0.105, 0.045, 0.13), eyes, "eye")
            part("uv_sphere", (x, -0.375, 1.755), (0.052, 0.025, 0.075), pupils, "pupil")
            part("uv_sphere", (x-0.025, -0.398, 1.79), (0.018, 0.012, 0.022), eyes, "eye highlight")
        part("uv_sphere", (0, -0.345, 1.58), (0.07, 0.035, 0.045), skin, "nose")
        part("uv_sphere", (0, -0.331, 1.49), (0.11, 0.025, 0.025), material_for("Mia | smile", (0.42,0.08,0.07,1)), "smile")
        for x in (-0.34, 0.34):
            for j in range(3):
                part("uv_sphere", (x, 0.015, 1.46-j*0.12), (0.075,0.075,0.09), hair, "braid")
        part("uv_sphere", (-0.27, -0.285, 2.02), (0.11,0.045,0.08), yellow, "snail hair clip")
        part("torus", (-0.27, -0.335, 2.02), (0.045,0.018,0.045), material_for("Mia | clip spiral", (0.72,0.32,0.02,1)), "clip spiral")
        part("uv_sphere", (0, 0, 1.12), (0.31,0.25,0.36), shirt, "white t-shirt")
        part("cube", (0, -0.025, 0.99), (0.49,0.30,0.42), overalls, "overalls bib")
        for x in (-0.16, 0.16):
            part("cube", (x, -0.18, 1.22), (0.085,0.045,0.32), overalls, "overall strap")
            part("uv_sphere", (x, -0.208, 1.11), (0.035,0.025,0.035), yellow, "overall button")
            part("cylinder", (x, 0, 0.57), (0.095,0.10,0.52), skin, "leg")
            part("uv_sphere", (x, -0.10, 0.30), (0.16,0.23,0.12), yellow, "yellow sneaker")
        for x in (-0.39, 0.39):
            arm = part("cylinder", (x*1.12, -0.12, 1.12), (0.085,0.09,0.39), skin, "arm")
            arm.rotation_euler[1] = -0.55 if x < 0 else 0.55
        part("uv_sphere", (0, 0.27, 1.10), (0.28,0.18,0.34), pink, "pink backpack")
        part("uv_sphere", (0, 0.435, 1.10), (0.14,0.035,0.14), material_for("Mia | backpack snail symbol", (0.98,0.68,0.82,1)), "backpack emblem")
    elif kind == "person":
        skin = material_for("skin", (0.72, 0.45, 0.30, 1))
        part("uv_sphere", (0, 0, 1.68), (0.30, 0.30, 0.30), skin, "head")
        part("uv_sphere", (0, 0.03, 1.88), (0.32, 0.32, 0.20), material_for("hair", (0.18, 0.075, 0.025, 1)), "hair")
        part("cone", (0, 0, 1.03), (0.42, 0.42, 0.72), primary, "body")
        part("cylinder", (-0.16, 0, 0.35), (0.10, 0.10, 0.45), dark, "left leg")
        part("cylinder", (0.16, 0, 0.35), (0.10, 0.10, 0.45), dark, "right leg")
        part("cylinder", (-0.40, 0, 1.05), (0.09, 0.09, 0.42), primary, "left arm")
        part("cylinder", (0.40, 0, 1.05), (0.09, 0.09, 0.42), primary, "right arm")
    elif kind == "snail":
        part("uv_sphere", (0, 0, 0.38), (0.62, 0.32, 0.22), leaf, "foot")
        part("uv_sphere", (-0.10, 0, 0.66), (0.34, 0.34, 0.34), material_for("snail shell", (0.62,0.25,0.06,1)), "shell")
        part("cylinder", (0.38, 0, 0.62), (0.10, 0.10, 0.45), leaf, "neck")
        part("uv_sphere", (0.40, 0, 0.92), (0.20, 0.20, 0.20), primary, "head")
        for x in (0.31, 0.49):
            part("cylinder", (x, 0, 1.10), (0.035, 0.035, 0.20), leaf, "eye stalk")
            part("uv_sphere", (x, -0.03, 1.20), (0.06, 0.06, 0.06), material_for("snail eyes", (0.02,0.02,0.02,1)), "eye")
    elif kind == "scooter":
        yellow = material_for("scooter yellow", (0.98,0.66,0.02,1))
        for x in (-0.52, 0.52):
            wheel = part("torus", (x, 0, 0.16), (0.16,0.16,0.07), dark, "wheel")
            wheel.rotation_euler[0] = math.pi / 2
        part("cube", (0, 0, 0.28), (1.15,0.14,0.10), yellow, "deck")
        stem = part("cylinder", (0.45,0,0.68), (0.06,0.06,0.85), dark, "steering stem")
        stem.rotation_euler[1] = -0.18
        part("cube", (0.45,0,1.10), (0.42,0.09,0.08), yellow, "handlebar")
    elif kind == "bicycle":
        for x in (-0.62, 0.62):
            wheel = part("torus", (x,0,0.45), (0.40,0.40,0.06), dark, "wheel")
            wheel.rotation_euler[0] = math.pi / 2
        part("cylinder", (-0.10,0,0.48), (0.06,0.06,0.70), primary, "frame diagonal")
        part("cylinder", (0.28,0,0.48), (0.06,0.06,0.68), primary, "frame diagonal 2")
        part("cube", (-0.10,0,0.90), (0.30,0.10,0.08), dark, "seat")
        part("cylinder", (0.62,0,0.85), (0.05,0.05,0.50), dark, "handle stem")
        part("cube", (0.62,0,1.10), (0.36,0.08,0.06), dark, "handlebar")
    elif kind == "fish":
        part("uv_sphere", (0,0,0), (0.72,0.34,0.40), primary, "body")
        tail = part("cone", (-0.78,0,0), (0.38,0.38,0.38), material_for("fish tail",(1.0,0.45,0.08,1)), "tail")
        tail.rotation_euler[1] = math.pi / 2
        part("uv_sphere", (0.35,-0.29,0.10), (0.07,0.07,0.07), material_for("fish eye",(0.01,0.01,0.01,1)), "eye")
    elif kind == "cactus":
        part("cylinder", (0,0,0.78), (0.26,0.26,1.55), leaf, "stem")
        part("cylinder", (-0.32,0,0.78), (0.12,0.12,0.55), leaf, "left arm")
        part("cylinder", (-0.22,0,1.02), (0.12,0.12,0.28), leaf, "left arm tip")
        part("cylinder", (0.32,0,0.98), (0.12,0.12,0.48), leaf, "right arm")
        part("cylinder", (0.22,0,1.18), (0.12,0.12,0.25), leaf, "right arm tip")
    elif kind == "snowman":
        snow = material_for("snow", (0.90,0.94,0.98,1))
        part("uv_sphere", (0,0,0.48), (0.52,0.52,0.52), snow, "base")
        part("uv_sphere", (0,0,1.15), (0.38,0.38,0.38), snow, "middle")
        part("uv_sphere", (0,0,1.66), (0.28,0.28,0.28), snow, "head")
        nose = part("cone", (0,-0.30,1.66), (0.10,0.10,0.30), roof, "nose")
        nose.rotation_euler[0] = math.pi/2
        part("cylinder", (0,0,1.98), (0.36,0.36,0.12), dark, "hat brim")
        part("cylinder", (0,0,2.16), (0.24,0.24,0.30), dark, "hat")
        for x in (-0.10,0.10): part("uv_sphere",(x,-0.25,1.72),(0.035,0.035,0.035),dark,"eye")
    elif kind == "castle":
        stone = primary
        part("cube",(0,0,0.90),(2.1,1.6,1.8),stone,"keep")
        for x in (-0.85,0.85):
            for y in (-0.60,0.60):
                part("cylinder",(x,y,1.35),(0.28,0.28,2.7),stone,"tower")
                part("cone",(x,y,2.95),(0.38,0.38,0.55),roof,"tower roof")
        part("cube",(0,-0.82,0.50),(0.42,0.08,0.95),wood,"gate")
    elif kind == "sofa":
        part("cube",(0,0,0.42),(1.9,0.85,0.45),primary,"base")
        part("cube",(0,0.36,0.92),(1.9,0.16,0.80),primary,"back")
        for x in (-0.88,0.88): part("cube",(x,0,0.70),(0.18,0.92,0.52),primary,"arm")
        for x in (-0.45,0.45): part("cube",(x,-0.10,0.70),(0.78,0.64,0.18),material_for("sofa cushions",(0.55,0.20,0.60,1)),"cushion")
    elif kind == "submarine":
        yellow = material_for("submarine yellow",(0.95,0.58,0.025,1))
        body = part("uv_sphere",(0,0,0),(1.15,0.48,0.48),yellow,"hull")
        part("cube",(0,0,0.48),(0.40,0.30,0.35),yellow,"conning tower")
        for x in (-0.48,0,0.48):
            port = part("torus",(x,-0.44,0),(0.15,0.15,0.05),glass,"porthole")
            port.rotation_euler[0] = math.pi/2
    elif kind == "coral":
        coral = material_for("coral pink",(0.92,0.12,0.34,1))
        part("cylinder",(0,0,0.45),(0.15,0.15,0.90),coral,"stem")
        for x,z in [(-0.25,0.72),(0.25,0.85),(-0.15,1.10),(0.28,1.28)]:
            branch = part("cylinder",(x,0,z),(0.09,0.09,0.52),coral,"branch")
            branch.rotation_euler[1] = -0.4 if x < 0 else 0.4
    elif kind == "swing":
        part("cylinder",(-0.75,0,1.0),(0.08,0.08,2.0),wood,"left post")
        part("cylinder",(0.75,0,1.0),(0.08,0.08,2.0),wood,"right post")
        part("cylinder",(0,0,1.95),(0.08,0.08,1.65),wood,"top beam")
        for x in (-0.32,0.32): part("cylinder",(x,0,1.0),(0.025,0.025,1.75),dark,"rope")
        part("cube",(0,0,0.16),(0.85,0.35,0.10),primary,"seat")
    elif kind == "slide":
        part("cube",(0,0,0.16),(0.95,0.95,0.12),dark,"base")
        ramp = part("cube",(0,-0.35,0.70),(0.65,1.2,0.12),primary,"sliding ramp")
        ramp.rotation_euler[0] = -0.35
        part("cube",(0,0.35,1.12),(0.65,0.12,1.7),primary,"platform")
        for x in (-0.38,0.38): part("cylinder",(x,0.35,1.1),(0.05,0.05,1.65),dark,"rail")
    elif kind in ("sun", "moon", "star"):
        obj = add_prim("uv_sphere" if kind != "star" else "rock", location, (s, s, s), primary, item["name"])
        made.append(obj)
    return made

def _grid_location(index, total, aspect, layout):
    if layout == "circle":
        angle = math.tau * index / max(1, total)
        return (math.cos(angle) * max(2.0, total * 0.28), math.sin(angle) * max(2.0, total * 0.28), 1.0)
    if layout == "grid" or (layout == "auto" and aspect == "1:1"):
        columns = max(1, math.ceil(math.sqrt(total)))
        rows = math.ceil(total / columns)
        return ((index % columns - (columns - 1) / 2) * 2.7,
                ((index // columns) - (rows - 1) / 2) * 2.7, 0.8)
    if aspect == "9:16":
        return (0.0, 0.0, 0.8 + index * 2.5)
    if layout == "line" or layout == "auto":
        return ((index - (total - 1) / 2) * 2.7, 0.0, 0.8)
    columns = max(1, math.ceil(math.sqrt(total)))
    rows = math.ceil(total / columns)
    return ((index % columns - (columns - 1) / 2) * 2.7,
            ((index // columns) - (rows - 1) / 2) * 2.7, 0.8)

made_by_item = []
riding = bool(cfg.get("relationships", {}).get("mia_riding_scooter"))
for index, item in enumerate(cfg["objects"]):
    if riding and item["primitive"] == "mia":
        loc = (-0.15, -0.05, 0.18)
    elif riding and item["primitive"] == "scooter":
        loc = (-0.10, 0.0, 0.0)
    elif riding and item["primitive"] == "snail":
        loc = (1.45, 0.15, 0.0)
    else:
        loc = _grid_location(index, len(cfg["objects"]), cfg["aspect_ratio"], cfg.get("layout", "auto"))
    made = make_item(item, loc, index)
    root = bpy.data.objects.new("Agent Root | " + item["name"], None)
    scene.collection.objects.link(root)
    root.location = loc
    bpy.context.view_layer.update()
    for obj in made:
        obj.parent = root
        obj.matrix_parent_inverse = root.matrix_world.inverted()
    made_by_item.append((item, root))

# Build a simple environment from the prompt without external assets.
environment = cfg.get("environment", "auto")
style = cfg.get("style", "balanced")
lighting = cfg.get("lighting", "soft")
floor_color = (0.12, 0.14, 0.17, 1.0)
if environment == "forest": floor_color = (0.055, 0.20, 0.065, 1.0)
elif environment == "island": floor_color = (0.78, 0.62, 0.32, 1.0)
elif environment == "mountains": floor_color = (0.18, 0.22, 0.19, 1.0)
elif environment == "underwater": floor_color = (0.025, 0.20, 0.34, 1.0)
elif environment == "desert": floor_color = (0.72, 0.48, 0.23, 1.0)
elif environment == "winter": floor_color = (0.82, 0.88, 0.94, 1.0)
elif environment == "village": floor_color = (0.18, 0.28, 0.12, 1.0)
elif environment == "playground": floor_color = (0.08, 0.34, 0.09, 1.0)
elif environment == "fantasy": floor_color = (0.12, 0.08, 0.20, 1.0)
elif environment == "room": floor_color = (0.28, 0.23, 0.18, 1.0)
elif environment == "city": floor_color = (0.18, 0.19, 0.21, 1.0)
elif style == "minimal": floor_color = (0.78, 0.80, 0.82, 1.0)
floor_material = material_for("environment floor", floor_color)
if cfg.get("ground", True):
    bpy.ops.mesh.primitive_plane_add(size=max(22.0, len(cfg["objects"]) * 4.0), location=(0, 0, -0.03))
    bpy.context.object.name = "Environment | floor"
    bpy.context.object.data.materials.append(floor_material)

if environment == "room":
    wall_mat = material_for("room walls", (0.72, 0.72, 0.69, 1.0))
    for loc, scale in [((0, 5, 3), (12, 0.15, 6)), ((-6, 0, 3), (0.15, 10, 6))]:
        bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
        wall = bpy.context.object
        wall.name = "Environment | wall"
        wall.scale = scale
        wall.data.materials.append(wall_mat)
elif environment == "forest":
    for j, (x, y) in enumerate([(-7, 3), (-5, 6), (-2, 5), (2, 6), (5, 4), (7, 1), (-7, -3), (7, -4)]):
        make_item({"primitive":"tree","scale":0.8,"color_name":"green","color":[0.055,0.31,0.09,1],"name":"Background tree %02d" % j}, (x,y,0), j)
elif environment == "city":
    for j, (x, y, h) in enumerate([(-8,4,3),(-6,5,5),(6,5,4),(8,3,6),(-8,-3,4),(8,-4,3)]):
        bmat = material_for("building %d" % j, (0.19 + 0.025*j, 0.22 + 0.02*j, 0.27 + 0.02*j, 1.0))
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x,y,h/2))
        building = bpy.context.object
        building.name = "Environment | building %02d" % j
        building.scale = (1.4,1.4,h)
        building.data.materials.append(bmat)
elif environment == "space":
    star_mat = material_for("starlight", (0.85,0.90,1.0,1.0), 0.2)
    for j, (x,y,z) in enumerate([(-7,3,5),(-5,6,7),(-2,4,6),(3,6,5),(6,3,7),(7,-2,5),(-6,-4,6),(1,-5,7)]):
        add_prim("uv_sphere",(x,y,z),(.07,.07,.07),star_mat,"Environment | star %02d" % j)
elif environment == "island":
    water = material_for("ocean", (0.025,0.20,0.34,1.0), 0.28, 0.05)
    bpy.ops.mesh.primitive_plane_add(size=45, location=(0,0,-0.20))
    bpy.context.object.name = "Environment | ocean"
    bpy.context.object.data.materials.append(water)
elif environment == "mountains":
    for j, (x,y,h) in enumerate([(-7,5,4),(-4,7,5),(4,7,4),(7,4,6),(-8,-1,3),(8,-2,4)]):
        add_prim("cone",(x,y,h/2),(2.6,2.4,h),material_for("distant mountain", (0.20,0.25,0.27,1.0)),"Environment | mountain %02d" % j)
elif environment == "underwater":
    for j, (x,y) in enumerate([(-6,3),(-4,-3),(4,4),(6,-2)]):
        make_item({"primitive":"coral","scale":0.8,"color_name":"pink","color":[0.92,0.12,0.34,1],"name":"Background coral %02d" % j}, (x,y,0), j)
    for j, (x,y,z) in enumerate([(-4,1,2),(3,2,3),(5,-3,2)]):
        make_item({"primitive":"fish","scale":0.65,"color_name":"orange","color":[1.0,0.30,0.06,1],"name":"Background fish %02d" % j}, (x,y,z), j)
elif environment == "desert":
    sand = material_for("dune sand",(0.78,0.55,0.29,1.0))
    for j, (x,y,h) in enumerate([(-7,4,2.8),(-4,7,3.6),(5,6,3.2),(8,1,2.4),(-8,-3,2.2)]):
        add_prim("cone",(x,y,h/2),(3.5,2.4,h),sand,"Environment | dune %02d" % j)
elif environment == "winter":
    for j, (x,y) in enumerate([(-7,3),(-5,5),(5,5),(7,2),(-7,-3),(7,-4)]):
        make_item({"primitive":"tree","scale":0.8,"color_name":"green","color":[0.055,0.22,0.12,1],"name":"Snowy tree %02d" % j}, (x,y,0), j)
elif environment == "village":
    for j, (x,y) in enumerate([(-7,3),(-4,5),(5,5),(7,2),(-7,-3),(7,-4)]):
        make_item({"primitive":"house","scale":0.7,"color_name":"brown","color":[0.42,0.24,0.12,1],"name":"Village house %02d" % j}, (x,y,0), j)
elif environment == "playground":
    for j, (x,y) in enumerate([(-6,3),(6,3),(-6,-3),(6,-3)]):
        make_item({"primitive":"tree","scale":0.7,"color_name":"green","color":[0.055,0.31,0.09,1],"name":"Playground tree %02d" % j}, (x,y,0), j)
elif environment == "fantasy":
    for j, (x,y,z) in enumerate([(-7,4,4),(-4,6,5),(5,6,5),(8,2,4)]):
        add_prim("cone",(x,y,z/2),(2.5,2.5,z),material_for("fantasy mountain",(0.16,0.12,0.30,1)),"Fantasy | mountain %02d" % j)

total = max(1, len(cfg["objects"]))
camera_distance = max(10.0, total * (1.6 if cfg["aspect_ratio"] != "9:16" else 0.75))
if cfg.get("camera_angle") == "top":
    camera_location = (0.01, -0.01, max(12.0, total * 3.0))
    target = Vector((0.0, 0.0, 0.5))
elif cfg["aspect_ratio"] == "9:16":
    target_height = (total - 1) * 1.15 + 1.0
    camera_location = (camera_distance * 0.45, -camera_distance, target_height + 3.0)
    target = Vector((0.0, 0.0, target_height))
else:
    camera_location = (camera_distance * 0.55, -camera_distance * 0.95, camera_distance * 0.68)
    target = Vector((0.0, 0.0, 0.9))
bpy.ops.object.camera_add(location=camera_location)
camera = bpy.context.object
camera.name = "Camera | generated scene"
camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.lens = 50
scene.camera = camera

# Optional quoted title, parsed as inert text; it is not interpreted as code.
label_text = cfg.get("text_content", "")
if label_text:
    text_curve = bpy.data.curves.new("Agent | title text", type="FONT")
    text_curve.body = label_text[:100]
    text_curve.align_x = "CENTER"
    text_curve.size = 0.65
    text_curve.extrude = 0.006
    text_obj = bpy.data.objects.new("Agent | title text", text_curve)
    scene.collection.objects.link(text_obj)
    text_obj.rotation_euler = camera.rotation_euler.copy()
    text_obj.location = camera.location + camera.rotation_euler.to_matrix() @ Vector((0.0, 0.0, -6.0))
    text_curve.materials.append(material_for("title text", (0.96, 0.78, 0.28, 1.0)))

bpy.ops.object.light_add(type="AREA", location=(-4.0, -4.0, 8.0))
key = bpy.context.object
key.name = "Light | key"
if lighting == "night":
    key.data.energy, key.data.color = 850, (0.42, 0.55, 1.0)
elif lighting == "sunset":
    key.data.energy, key.data.color = 1500, (1.0, 0.48, 0.22)
elif lighting == "cinematic":
    key.data.energy, key.data.color = 1750, (0.72, 0.82, 1.0)
else:
    key.data.energy, key.data.color = 1250, (1.0, 0.93, 0.82)
key.data.shape = "DISK"
key.data.size = 6
key.rotation_euler = (Vector((0, 0, 0.5)) - key.location).to_track_quat("-Z", "Y").to_euler()
bpy.ops.object.light_add(type="AREA", location=(5.0, 3.0, 5.0))
fill = bpy.context.object
fill.name = "Light | fill"
fill.data.energy = 260 if lighting == "night" else 380 if lighting == "cinematic" else 650
fill.data.color = (0.30, 0.42, 1.0) if lighting == "night" else (1.0, 0.58, 0.30) if lighting == "sunset" else (0.78, 0.86, 1.0)
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
scene.world.color = tuple(cfg.get("world_color", [0.055, 0.055, 0.055, 1.0])[:3])
scene.world.use_nodes = True
background = scene.world.node_tree.nodes.get("Background") if scene.world.node_tree else None
if background:
    background.inputs["Color"].default_value = tuple(cfg.get("world_color", [0.055, 0.055, 0.055, 1.0]))
    background.inputs["Strength"].default_value = 0.18 if lighting == "night" else 0.45
scene.render.film_transparent = bool(cfg.get("transparent_background", False))
if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
    scene.eevee.taa_render_samples = 64 if cfg["render_percentage"] >= 75 else 32
scene.render.fps = 30
animation = cfg.get("animation", {})
if animation.get("enabled"):
    scene.frame_start = 1
    scene.frame_end = max(24, min(240, int(animation.get("frames", 120))))
    animated = [root for item, root in made_by_item if not riding or item["primitive"] in ("mia", "scooter")]
    for obj in animated:
        obj.location = obj.location.copy()
        obj.keyframe_insert(data_path="location", frame=scene.frame_start)
        obj.rotation_euler = obj.rotation_euler.copy()
        obj.keyframe_insert(data_path="rotation_euler", frame=scene.frame_start)
        if animation.get("kind") == "rotate":
            obj.rotation_euler.z += math.tau
        elif animation.get("kind") == "move":
            obj.location.x += 4.0 if riding else 2.0
        else:
            obj.location.z += 1.5
        obj.keyframe_insert(data_path="location", frame=scene.frame_end)
        obj.keyframe_insert(data_path="rotation_euler", frame=scene.frame_end)
    scene.frame_set(1)
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
        "environment": cfg.get("environment", "auto"),
        "style": cfg.get("style", "balanced"),
        "lighting": cfg.get("lighting", "soft"),
        "animation_enabled": bool(cfg.get("animation", {}).get("enabled")),
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
                    if manifest.get("status") == "failed":
                        raise SceneRequestError("Blender отклонил создание сцены: " + str(manifest.get("error", "неизвестная ошибка"))[:1800])
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
