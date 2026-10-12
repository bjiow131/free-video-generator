"""Bounded Blender workflow helpers for local discovery and Mia blockout creation.

All Blender scripts are bundled here as fixed code. Remote task arguments are
validated data only; no task can provide Python source, shell commands, or paths.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import struct
import tempfile
import time
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
hair=mat("Mia | light brown hair",(0.36,0.20,0.10))
jacket=mat("Mia | teal-blue jacket",(0.035,0.32,0.40))
pants=mat("Mia | brown trousers",(0.24,0.13,0.075))
backpack=mat("Mia | mustard-yellow backpack",(0.78,0.48,0.055))
shoe=mat("Mia | sturdy ankle boots",(0.16,0.085,0.045))
white=mat("Eyes | ivory",(0.95,0.88,0.73))
iris=mat("Eyes | brown",(0.19,0.08,0.035))
yellow=mat("Scooter | sunny yellow",(1.0,0.62,0.05),0.38)
metal=mat("Scooter | metal",(0.20,0.23,0.24),0.4)
snail=mat("Snail | soft green",(0.35,0.53,0.27))
shell=mat("Snail | amber shell",(0.67,0.31,0.12))
stepa_jacket=mat("Stepa | forest green top",(0.12,0.30,0.19))
stepa_accent=mat("Stepa | muted orange accents",(0.72,0.28,0.09))
stepa_pants=mat("Stepa | olive trousers",(0.24,0.25,0.14))
pathmat=mat("Environment | flat path",(0.48,0.45,0.38))
grassmat=mat("Environment | grass",(0.18,0.35,0.12))
housemat=mat("Environment | house",(0.70,0.58,0.42))
roofmat=mat("Environment | roof",(0.28,0.16,0.12))
marker_orange=mat("Prop | marker orange",(0.90,0.24,0.06))
marker_white=mat("Prop | marker white",(0.92,0.88,0.74))
bookmat=mat("Prop | discovery book",(0.35,0.44,0.18))
pencilmat=mat("Prop | pencils",(0.88,0.35,0.08))
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
def box(name, loc, dims, material):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o=bpy.context.object; o.name=name; o.dimensions=dims
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    o.data.materials.append(material); return o
# Mia: deliberately simple, editable proportions; not a finished production mesh.
uv("Mia | head",(0,0,3.12),(0.53,0.47,0.58),skin)
uv("Mia | hair cap",(0,0.035,3.48),(0.55,0.48,0.32),hair)
uv("Mia | back hair",(0,0.23,3.13),(0.48,0.28,0.62),hair)
# The approved Mia turnaround has a loose low bun and no helmet.
uv("Mia | low bun",(0,0.39,3.13),(0.25,0.22,0.23),hair)
for i, (dx,dz) in enumerate(((-0.12,0.02),(-0.05,0.13),(0.05,0.14),(0.13,0.04),(0.02,-0.10),(-0.10,-0.09))):
    uv("Mia | bun curl %02d" % i,(dx,0.47,3.13+dz),(0.105,0.11,0.105),hair,16,10)
uv("Mia | mustard backpack",(0,0.32,2.31),(0.27,0.16,0.34),backpack)
uv("Mia | fringe left",(-0.24,-0.405,3.43),(0.25,0.12,0.19),hair)
uv("Mia | fringe right",(0.08,-0.425,3.45),(0.24,0.11,0.17),hair)
for x in (-0.21,0.21):
    uv("Mia | eye white",(x,-0.423,3.16),(0.125,0.065,0.15),white,24,16)
    uv("Mia | iris",(x,-0.477,3.15),(0.071,0.036,0.092),iris,20,12)
    uv("Mia | pupil",(x,-0.508,3.15),(0.039,0.022,0.058),mat("Mia | pupil black",(0.035,0.018,0.012)),16,10)
    uv("Mia | eye catchlight",(x-0.025,-0.528,3.19),(0.019,0.012,0.024),white,12,8)
for x in (-0.21,0.21):
    brow=uv("Mia | soft eyebrow",(x,-0.425,3.36),(0.105,0.04,0.032),hair,16,10)
    brow.rotation_euler[1]=0.10 if x < 0 else -0.10
for x in (-0.34,0.34):
    uv("Mia | rosy cheek",(x,-0.394,3.01),(0.095,0.035,0.055),mat("Mia | rosy skin",(0.92,0.40,0.32)),16,10)
uv("Mia | nose",(0,-0.49,3.02),(0.055,0.045,0.06),skin,16,10)
uv("Mia | smile",(0,-0.466,2.91),(0.095,0.025,0.027),mat("Mia | warm smile",(0.36,0.09,0.075)),16,10)
uv("Mia | jacket torso",(0,0,2.22),(0.37,0.29,0.57),jacket)
uv("Mia | neck",(0,0,2.77),(0.13,0.13,0.17),skin)
between("Mia | hoodie zipper",(0,-0.294,1.80),(0,-0.294,2.60),0.012,mat("Mia | zipper brass",(0.84,0.51,0.12)))
uv("Mia | hood",(0,0.16,2.57),(0.31,0.18,0.22),jacket)
for side in (-1,1):
    hip=(side*0.19,0,1.72); knee=(side*0.21,-0.015,1.05); ankle=(side*0.22,-0.02,0.48)
    between("Mia | trouser leg",hip,knee,0.105,pants); between("Mia | trouser cuff",knee,ankle,0.085,pants)
    uv("Mia | shoe",(side*0.22,-0.10,0.34),(0.15,0.24,0.10),shoe)
    shoulder=(side*0.32,0,2.55); elbow=(side*0.48,-0.015,2.22); hand=(side*0.52,-0.04,2.03)
    between("Mia | jacket sleeve",shoulder,elbow,0.105,jacket); between("Mia | jacket cuff",elbow,hand,0.075,jacket)
    uv("Mia | hand",hand,(0.09,0.08,0.10),skin)
# Yellow scooter to preserve the character bible.
between("Scooter | deck",(-0.2,-0.72,0.35),(0.62,-0.72,0.35),0.055,yellow)
for x in (-0.12,0.55):
    o=cyl("Scooter | wheel",(x,-0.72,0.20),0.13,0.09,shoe,24); o.rotation_euler[0]=math.pi/2
between("Scooter | stem",(0.52,-0.72,0.35),(0.57,-0.72,0.93),0.035,metal)
between("Scooter | handle", (0.42,-0.72,0.93),(0.72,-0.72,0.93),0.035,yellow)
# Stepa: distinct preschool proxy with generated-draft color blocking.
uv("Stepa | head",(-2.05,0,3.12),(0.52,0.46,0.57),skin)
uv("Stepa | hair cap",(-2.05,0.035,3.47),(0.55,0.47,0.30),hair)
uv("Stepa | back hair",(-2.05,0.23,3.12),(0.48,0.28,0.60),hair)
for x in (-2.24,-1.86):
    uv("Stepa | eye white",(x,-0.435,3.16),(0.09,0.045,0.10),white,20,12)
    uv("Stepa | iris",(x,-0.475,3.15),(0.044,0.022,0.057),iris,16,10)
uv("Stepa | jacket torso",(-2.05,0,2.22),(0.37,0.29,0.56),stepa_jacket)
uv("Stepa | neck",(-2.05,0,2.76),(0.13,0.13,0.17),skin)
for side in (-1,1):
    hip=(-2.05+side*0.19,0,1.72); knee=(-2.05+side*0.21,-0.015,1.05); ankle=(-2.05+side*0.22,-0.02,0.48)
    between("Stepa | trouser leg",hip,knee,0.105,stepa_pants); between("Stepa | trouser cuff",knee,ankle,0.085,stepa_pants)
    uv("Stepa | shoe",(-2.05+side*0.22,-0.10,0.34),(0.15,0.24,0.10),shoe)
    shoulder=(-2.05+side*0.32,0,2.55); elbow=(-2.05+side*0.48,-0.015,2.22); hand=(-2.05+side*0.52,-0.04,2.03)
    between("Stepa | sleeve",shoulder,elbow,0.105,stepa_jacket); between("Stepa | orange cuff",elbow,hand,0.075,stepa_accent)
    uv("Stepa | hand",hand,(0.09,0.08,0.10),skin)
# Two simple race markers at the start line.
for i, x in enumerate((-1.35, 1.35)):
    bpy.ops.mesh.primitive_cone_add(vertices=16, radius1=0.17, radius2=0.035, depth=0.38, location=(x,-1.05,0.21))
    cone=bpy.context.object; cone.name=f"Prop | race marker {i+1}"; cone.data.materials.append(marker_orange)
    cyl(f"Prop | marker band {i+1}",(x,-1.05,0.22),0.125,0.08,marker_white,16)
# Episode inventory proxies staged outside the first-scene camera.
box("Prop | discovery book cover",(7,5,0.12),(0.55,0.42,0.08),bookmat)
for i in range(3):
    between(f"Prop | pencil {i+1}",(7.65+i*0.11,5,0.08),(7.65+i*0.11,5,0.42),0.025,pencilmat)
# Friendly stylized snail companion; hidden from this opening race scene.
uv("Snail | body",(1.55,-0.1,0.25),(0.42,0.20,0.16),snail)
uv("Snail | head",(1.84,-0.1,0.43),(0.14,0.14,0.21),snail)
uv("Snail | shell",(1.49,-0.11,0.48),(0.27,0.25,0.27),shell)
for x in (1.79,1.91):
    between("Snail | eye stalk",(x,-0.1,0.55),(x,-0.1,0.67),0.025,snail)
    uv("Snail | eye",(x,-0.13,0.69),(0.035,0.03,0.04),white,12,8)
# Rigid per-part proxy rigs for this scene blockout. These are editable
# placeholders, not smooth production skinning.
def build_rig(name, prefix, origin, bones):
    data=bpy.data.armatures.new(name)
    arm=bpy.data.objects.new(name,data)
    bpy.context.scene.collection.objects.link(arm)
    arm.location=origin
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active=arm; arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    made={}
    for bone_name, head, tail, parent in bones:
        b=data.edit_bones.new(bone_name); b.head=head; b.tail=tail; made[bone_name]=b
    for bone_name, head, tail, parent in bones:
        if parent: made[bone_name].parent=made[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.show_in_front=True; data.display_type="OCTAHEDRAL"
    bound=[]
    for obj in list(bpy.context.scene.objects):
        if obj.type!="MESH" or not obj.name.startswith(prefix+" |"): continue
        label=obj.name[len(prefix)+2:].lower()
        relative_x=obj.matrix_world.translation.x-origin[0]
        side=".L" if relative_x>=0 else ".R"
        bone=None
        if prefix in ("Mia","Stepa"):
            if "eye white" in label or "iris" in label or "pupil" in label or "catchlight" in label: bone="eye"+side
            elif any(w in label for w in ("head","hair","fringe","nose","bun","eyebrow","cheek","smile")): bone="head"
            elif "neck" in label: bone="neck"
            elif any(w in label for w in ("backpack","torso")): bone="spine"
            elif "sleeve" in label: bone="upper_arm"+side
            elif "hand" in label: bone="hand"+side
            elif "cuff" in label: bone="forearm"+side
            elif "trouser leg" in label: bone="thigh"+side
            elif "trouser cuff" in label: bone="shin"+side
            elif "shoe" in label: bone="foot"+side
        else:
            if "body" in label or "shell" in label: bone="body"
            elif "head" in label: bone="head"
            elif "stalk" in label or "eye" in label:
                bone="eye.L" if relative_x<0.34 else "eye.R"
        if bone is None or bone not in data.bones:
            continue
        group=obj.vertex_groups.new(name=bone)
        if len(obj.data.vertices): group.add(list(range(len(obj.data.vertices))),1.0,"REPLACE")
        mod=obj.modifiers.new(name=name+" rigid proxy binding",type="ARMATURE"); mod.object=arm
        bound.append(obj.name)
    return arm,bound
child_bones=[
    ("root",(0,0,0.15),(0,0,0.55),None),
    ("pelvis",(0,0,1.45),(0,0,1.78),"root"),
    ("spine",(0,0,1.78),(0,0,2.35),"pelvis"),
    ("neck",(0,0,2.35),(0,0,2.65),"spine"),
    ("head",(0,0,2.65),(0,0,3.35),"neck"),
    ("jaw",(0,-0.08,2.90),(0,-0.10,3.04),"head"),
    ("eye.L",(0.08,-0.39,3.12),(0.18,-0.39,3.12),"head"),
    ("eye.R",(-0.08,-0.39,3.12),(-0.18,-0.39,3.12),"head"),
    ("upper_arm.L",(0.30,0,2.25),(0.62,0,1.93),"spine"),
    ("forearm.L",(0.62,0,1.93),(0.78,0,1.60),"upper_arm.L"),
    ("hand.L",(0.52,-0.04,2.03),(0.60,-0.04,1.96),"forearm.L"),
    ("upper_arm.R",(-0.30,0,2.25),(-0.62,0,1.93),"spine"),
    ("forearm.R",(-0.62,0,1.93),(-0.78,0,1.60),"upper_arm.R"),
    ("hand.R",(-0.52,-0.04,2.03),(-0.60,-0.04,1.96),"forearm.R"),
    ("thigh.L",(0.18,0,1.48),(0.20,0,0.88),"pelvis"),
    ("shin.L",(0.20,0,0.88),(0.20,0,0.22),"thigh.L"),
    ("foot.L",(0.22,-0.10,0.34),(0.22,-0.30,0.30),"shin.L"),
    ("thigh.R",(-0.18,0,1.48),(-0.20,0,0.88),"pelvis"),
    ("shin.R",(-0.20,0,0.88),(-0.20,0,0.22),"thigh.R"),
    ("foot.R",(-0.22,-0.10,0.34),(-0.22,-0.30,0.30),"shin.R"),
]
mia_rig,mia_bound=build_rig("Mia_Rig","Mia",(0,0,0),child_bones)
stepa_rig,stepa_bound=build_rig("Stepa_Rig","Stepa",(-2.05,0,0),child_bones)
snail_bones=[
    ("root",(0,0,0.03),(0,0,0.16),None),
    ("body",(0,0,0.16),(0.16,0,0.35),"root"),
    ("head",(0.16,0,0.35),(0.31,0,0.55),"body"),
    ("eye.L",(0.27,0,0.50),(0.27,0,0.74),"head"),
    ("eye.R",(0.40,0,0.50),(0.40,0,0.74),"head"),
]
snail_rig,snail_bound=build_rig("Spiral_Rig","Snail",(1.5,-0.1,0),snail_bones)
for rig in (mia_rig,stepa_rig):
    bpy.context.view_layer.objects.active=rig
    bpy.ops.object.mode_set(mode="POSE")
    test_bone=rig.pose.bones["forearm.L"]; test_bone.rotation_mode="XYZ"
    test_bone.rotation_euler[1]=0.12; bpy.context.view_layer.update()
    test_bone.rotation_euler=(0.0,0.0,0.0); bpy.context.view_layer.update()
    bpy.ops.object.mode_set(mode="OBJECT")
proxy_rig_count=3
proxy_bound_count=len(mia_bound)+len(stepa_bound)+len(snail_bound)
# Yard stage: wide level route, grass edges, and a simple home facade.
bpy.ops.mesh.primitive_plane_add(size=16, location=(0,0,0.01))
bpy.context.object.name="Environment | ground"; bpy.context.object.data.materials.append(groundmat)
box("Environment | flat yard path",(0,0,0.045),(12,2.8,0.08),pathmat)
box("Environment | grass edge near",(0,-2.0,0.035),(12,1.2,0.05),grassmat)
box("Environment | grass edge far",(0,2.0,0.035),(12,1.2,0.05),grassmat)
box("Environment | home facade",(0,4.4,2.05),(8,0.35,4.1),housemat)
box("Environment | roofline",(0,4.4,4.18),(8.5,0.55,0.28),roofmat)
for x in (-2.4,2.4): box("Environment | window",(x,4.19,2.65),(1.1,0.06,1.0),white)
for obj in bpy.context.scene.objects:
    if obj.name.startswith("Snail |"):
        obj.hide_render=True
# Ground, camera and lights.
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
               "object_count":len(bpy.context.scene.objects),"stage":"episode1_scene1_blockout",
               "proxy_rig_count":proxy_rig_count,"bound_mesh_count":proxy_bound_count},f)
'''



def _episode1_animation_script() -> str:
    """Fixed silent animatic pass; inputs are local paths constructed by this module."""
    return r'''
import bpy, json, math, os, sys, hashlib, shutil, subprocess, tempfile
from mathutils import Vector
args=sys.argv[sys.argv.index("--")+1:]
cfg=json.load(open(args[0],encoding="utf-8"))
out=os.path.realpath(cfg["output_dir"])
bpy.ops.wm.open_mainfile(filepath=os.path.join(out,"mia_blockout.blend"),load_ui=False)
scene=bpy.context.scene
duration_seconds=int(cfg.get("duration_seconds",60))
frame_count=duration_seconds*12
scene.frame_start=1; scene.frame_end=frame_count; scene.render.fps=12
scene.render.resolution_x=720; scene.render.resolution_y=1280; scene.render.resolution_percentage=100
scene.render.image_settings.file_format="PNG"
scene.render.filepath=os.path.join(out,"preview.png")
# Upgrade the already-saved 13-bone blockout in place. This keeps the existing
# scene and its user data while adding the new face, hand and foot controls.
def upgrade_child_rig(rig_name,prefix):
    rig=scene.objects.get(rig_name)
    if rig is None or rig.type!="ARMATURE": raise RuntimeError("Child rig missing: "+rig_name)
    controls=[
        ("jaw",(0,-0.08,2.90),(0,-0.10,3.04),"head"),
        ("eye.L",(0.08,-0.39,3.12),(0.18,-0.39,3.12),"head"),
        ("eye.R",(-0.08,-0.39,3.12),(-0.18,-0.39,3.12),"head"),
        ("hand.L",(0.52,-0.04,2.03),(0.60,-0.04,1.96),"forearm.L"),
        ("hand.R",(-0.52,-0.04,2.03),(-0.60,-0.04,1.96),"forearm.R"),
        ("foot.L",(0.22,-0.10,0.34),(0.22,-0.30,0.30),"shin.L"),
        ("foot.R",(-0.22,-0.10,0.34),(-0.22,-0.30,0.30),"shin.R"),
    ]
    bpy.ops.object.select_all(action="DESELECT"); rig.select_set(True); bpy.context.view_layer.objects.active=rig
    bpy.ops.object.mode_set(mode="EDIT")
    for name,head,tail,parent in controls:
        if name not in rig.data.edit_bones:
            bone=rig.data.edit_bones.new(name); bone.head=head; bone.tail=tail
            bone.parent=rig.data.edit_bones.get(parent)
    bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(scene.objects):
        if obj.type!="MESH" or not obj.name.startswith(prefix+" | "): continue
        label=obj.name[len(prefix)+2:].lower(); relx=obj.matrix_world.translation.x-rig.location.x
        side=".L" if relx>=0 else ".R"
        if "eye white" in label or "iris" in label or "pupil" in label or "catchlight" in label: bone="eye"+side
        elif any(w in label for w in ("head","hair","fringe","nose","bun","eyebrow","cheek","smile")): bone="head"
        elif "neck" in label: bone="neck"
        elif any(w in label for w in ("backpack","torso")): bone="spine"
        elif "sleeve" in label: bone="upper_arm"+side
        elif "hand" in label: bone="hand"+side
        elif "cuff" in label: bone="forearm"+side
        elif "trouser leg" in label: bone="thigh"+side
        elif "trouser cuff" in label: bone="shin"+side
        elif "shoe" in label: bone="foot"+side
        else: continue
        for group in list(obj.vertex_groups): obj.vertex_groups.remove(group)
        group=obj.vertex_groups.new(name=bone)
        if obj.data.vertices: group.add(list(range(len(obj.data.vertices))),1.0,"REPLACE")
        modifier=next((m for m in obj.modifiers if m.type=="ARMATURE"),None)
        if modifier is None: modifier=obj.modifiers.new(name=rig_name+" rigid proxy binding",type="ARMATURE")
        modifier.object=rig
    missing={"jaw","eye.L","eye.R","hand.L","hand.R","foot.L","foot.R"}-set(rig.data.bones.keys())
    if missing: raise RuntimeError("Child rig upgrade incomplete: "+",".join(sorted(missing)))
    return len(rig.data.bones)
mia_bone_count=upgrade_child_rig("Mia_Rig","Mia")
stepa_bone_count=upgrade_child_rig("Stepa_Rig","Stepa")
def aim(camera, point):
    camera.rotation_euler=(Vector(point)-camera.location).to_track_quat("-Z","Y").to_euler()
camera=scene.camera
camera.data.type="ORTHO"; camera.data.ortho_scale=9.5
camera.location=(3.3,-12.5,4.7); aim(camera,(-0.25,0.1,1.85))
backpack=bpy.data.objects.get("Mia | mustard backpack")
if not backpack: raise RuntimeError("Mia backpack proxy is missing")
def material(name, rgba):
    m=bpy.data.materials.get(name)
    if m is None:
        m=bpy.data.materials.new(name); m.diffuse_color=rgba; m.use_nodes=True
        bs=m.node_tree.nodes.get("Principled BSDF")
        if bs: bs.inputs["Base Color"].default_value=rgba
    return m
gold=material("Mia | mustard strap",(0.90,0.56,0.08,1))
def bar(name,a,b,r,mat):
    vec=Vector(b)-Vector(a); mid=(Vector(a)+Vector(b))*0.5
    bpy.ops.mesh.primitive_cylinder_add(vertices=12,radius=r,depth=vec.length,location=mid)
    o=bpy.context.object; o.name=name; o.data.materials.append(mat)
    o.rotation_euler=vec.to_track_quat("Z","Y").to_euler(); return o
for sign in (-1,1):
    bar("Mia | visible backpack shoulder strap",(sign*0.25,-0.31,2.56),(sign*0.19,-0.31,2.05),0.055,gold)
skin=material("Guardian | neutral",(0.48,0.31,0.22,1))
coat=material("Guardian | muted coat",(0.22,0.29,0.31,1))
def box(name,loc,dims,mat):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc)
    o=bpy.context.object; o.name=name; o.dimensions=dims
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True); o.data.materials.append(mat); return o
def sphere(name,loc,scale,mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20,ring_count=12,location=loc)
    o=bpy.context.object; o.name=name; o.scale=scale; o.data.materials.append(mat); return o
gx,gy=1.85,2.05
box("Adult guardian proxy | torso",(gx,gy,1.62),(0.72,0.42,1.2),coat)
sphere("Adult guardian proxy | head",(gx,gy,2.55),(0.30,0.29,0.36),skin)
for s in (-1,1):
    box("Adult guardian proxy | leg",(gx+s*0.20,gy,0.62),(0.22,0.25,0.82),coat)
    bar("Adult guardian proxy | arm",(gx+s*0.39,gy,2.05),(gx+s*0.48,gy-0.05,1.45),0.09,coat)
# Keep the guardian as a scene reference only; the approved framing keeps adults off camera.
for obj in scene.objects:
    if obj.name.startswith("Adult guardian proxy"):
        obj.hide_render=True
mouth_mat=material("Face | mouth",(0.055,0.018,0.014,1))
def mouth_for(prefix,x,y,z):
    obj=sphere(prefix+" | mouth cue",(x,y,z),(0.105,0.025,0.025),mouth_mat)
    rig=scene.objects.get(prefix+"_Rig")
    if rig is None or "jaw" not in rig.data.bones: raise RuntimeError("Jaw control missing for "+prefix)
    group=obj.vertex_groups.new(name="jaw")
    if obj.data.vertices: group.add(list(range(len(obj.data.vertices))),1.0,"REPLACE")
    modifier=obj.modifiers.new(name=prefix+" jaw control",type="ARMATURE"); modifier.object=rig
    return obj
mia_mouth=mouth_for("Mia",0,-0.475,2.96)
step_mouth=mouth_for("Stepa",-2.05,-0.47,2.96)
def animate_mouth(obj, intervals):
    base=tuple(obj.scale)
    for start,end in intervals:
        for frame,opening in ((start,0.15),(start+3,1.0),(end-3,1.0),(end,0.15)):
            obj.scale=(base[0],base[1],base[2]*opening)
            obj.keyframe_insert(data_path="scale",frame=frame)
animate_mouth(step_mouth,[(20,125),(270,330),(390,475)])
animate_mouth(mia_mouth,[(130,255),(340,385),(485,545)])
def parent_group(prefixes,name):
    root=bpy.data.objects.new(name,None); scene.collection.objects.link(root)
    root.empty_display_type="PLAIN_AXES"; root.empty_display_size=0.5
    if name.startswith("Stepa_"):
        root.location.x=-2.05
    for obj in list(scene.objects):
        if any(obj.name.startswith(prefix) for prefix in prefixes) or obj.name == name.split("_",1)[0]+"_Rig":
            if obj is root: continue
            world=obj.matrix_world.copy(); obj.parent=root; obj.matrix_world=world
    return root
mia_root=parent_group(("Mia |","Scooter |"),"Mia_Root_animated")
step_root=parent_group(("Stepa |",),"Stepa_Root_animated")
for frame,x in ((1,0),(480,0),(540,0.25),(600,0.5),(720,0.5)):
    mia_root.location.x=x; mia_root.keyframe_insert(data_path="location",frame=frame)
for frame,tilt in ((1,0),(90,0),(120,0.06),(150,0),(300,0),(340,-0.05),(380,0),(720,0)):
    step_root.rotation_euler.z=tilt; step_root.keyframe_insert(data_path="rotation_euler",frame=frame)

# Pose controls animate actual rigid-bound character parts instead of moving
# only the parent group. The proxies remain segmented; this is a controllable
# scene rig, not a claim of production-quality smooth skinning.
def animate_bone(rig_name,bone_name,axis,keys):
    rig=scene.objects.get(rig_name)
    if rig is None or rig.type!="ARMATURE" or bone_name not in rig.pose.bones:
        raise RuntimeError("Required rig control is missing: "+rig_name+"/"+bone_name)
    bone=rig.pose.bones[bone_name]; bone.rotation_mode="XYZ"
    for frame,value in keys:
        rotation=[0.0,0.0,0.0]; rotation[axis]=value
        bone.rotation_euler=rotation
        bone.keyframe_insert(data_path="rotation_euler",frame=frame,group=bone_name)

animate_bone("Mia_Rig","upper_arm.L",1,((1,0),(28,0.28),(48,0.62),(72,0.72),(96,0.15),(120,0),(720,0)))
animate_bone("Mia_Rig","upper_arm.R",1,((1,0),(28,-0.28),(48,-0.62),(72,-0.72),(96,-0.15),(120,0),(720,0)))
animate_bone("Mia_Rig","forearm.L",2,((1,0),(42,-0.22),(72,-0.3),(100,0),(720,0)))
animate_bone("Mia_Rig","forearm.R",2,((1,0),(42,0.22),(72,0.3),(100,0),(720,0)))
animate_bone("Mia_Rig","head",2,((1,0),(72,0.04),(120,-0.08),(180,0),(380,0.09),(430,0),(720,0)))
animate_bone("Mia_Rig","eye.L",2,((1,0),(160,0.08),(210,0),(400,-0.07),(450,0),(720,0)))
animate_bone("Mia_Rig","eye.R",2,((1,0),(160,0.08),(210,0),(400,-0.07),(450,0),(720,0)))
animate_bone("Mia_Rig","jaw",0,((1,0),(140,0.08),(250,0),(355,0.07),(385,0),(500,0.08),(545,0),(720,0)))
animate_bone("Mia_Rig","foot.L",1,((1,0),(485,0.02),(540,0.04),(600,0.02),(720,0)))

# Stepa marks the start and gives a short countdown gesture; Mia answers and
# looks toward the route. These pose keys align with the existing dialogue cues.
animate_bone("Stepa_Rig","upper_arm.L",1,((1,0),(20,0.35),(80,0.55),(125,0),(270,0),(300,0.5),(330,0),(720,0)))
animate_bone("Stepa_Rig","forearm.L",2,((1,0),(25,-0.3),(70,0.35),(110,-0.2),(125,0),(270,0),(300,-0.5),(330,0),(720,0)))
animate_bone("Stepa_Rig","upper_arm.R",1,((1,0),(270,-0.35),(305,-0.58),(340,0),(390,-0.35),(430,-0.58),(475,0),(720,0)))
animate_bone("Stepa_Rig","forearm.R",2,((1,0),(270,0.3),(305,-0.35),(340,0),(390,0.3),(430,-0.35),(475,0),(720,0)))
animate_bone("Stepa_Rig","head",2,((1,0),(120,0.08),(180,0),(300,-0.1),(360,0),(475,0.08),(520,0),(720,0)))
animate_bone("Stepa_Rig","jaw",0,((1,0),(20,0),(45,0.08),(120,0),(270,0),(290,0.08),(330,0),(390,0),(410,0.08),(475,0),(720,0)))
for obj in scene.objects:
    if obj.name=="Scooter | wheel":
        for frame,angle in ((1,0),(480,0),(600,-math.pi*2),(720,-math.pi*2)):
            obj.rotation_euler.y=angle; obj.keyframe_insert(data_path="rotation_euler",frame=frame)
for frame,loc,scale in ((1,(3.3,-12.5,4.7),9.5),(180,(3.3,-12.3,4.6),9.5),
                        (360,(3.3,-11.8,4.4),9.2),(540,(3.3,-11.5,4.2),9.0),
                        (720,(3.3,-12.0,4.4),9.5)):
    camera.location=loc; camera.data.ortho_scale=scale; aim(camera,(-0.25,0.1,1.85))
    camera.keyframe_insert(data_path="location",frame=frame)
    camera.keyframe_insert(data_path="rotation_euler",frame=frame)
    camera.data.keyframe_insert(data_path="ortho_scale",frame=frame)
# The five-second test preserves the same story beats by compressing the full
# animatic timing; its 60 frames therefore show the complete action.
def action_fcurves(action):
    # Blender 5 stores animation curves on channelbags, not Action.fcurves.
    layers=getattr(action,"layers",())
    if layers:
        for layer in layers:
            for strip in layer.strips:
                for bag in getattr(strip,"channelbags",()):
                    yield from bag.fcurves
    else:
        yield from getattr(action,"fcurves",())
if duration_seconds != 60:
    ratio=duration_seconds/60.0
    for action in bpy.data.actions:
        for curve in action_fcurves(action):
            for point in curve.keyframe_points:
                point.co.x=1+(point.co.x-1)*ratio
                point.handle_left.x=1+(point.handle_left.x-1)*ratio
                point.handle_right.x=1+(point.handle_right.x-1)*ratio
            curve.update()
asset_root=os.path.realpath(cfg["asset_root"])
ref_meta={}
for key,rel in (("mia_passport","characters/passports/mia.json"),
                ("stepa_passport","characters/passports/stepa.json"),
                ("draft_board","references/episode-01-reference-board.png"),
                ("approved_mia_turnaround","references/mia_turnaround_approved_20261012.jpeg")):
    path=os.path.realpath(os.path.join(asset_root,rel))
    if os.path.commonpath((asset_root,path))!=asset_root or not os.path.isfile(path):
        raise RuntimeError("Required pinned Episode 1 reference asset is missing")
    with open(path,"rb") as f: raw=f.read()
    ref_meta[key]={"relative_path":rel,"sha256":hashlib.sha256(raw).hexdigest()}
    if key.endswith("passport"):
        data=json.loads(raw.decode("utf-8"))
        expected_id="mia" if key=="mia_passport" else "stepa"
        if data.get("character_id")!=expected_id or data.get("status")!="awaiting_original_references":
            raise RuntimeError("Unexpected character passport")
        if key=="mia_passport" and data.get("age_or_species")!="4 года":
            raise RuntimeError("Mia passport age does not match continuity")
    else:
        image=bpy.data.images.load(path,check_existing=True); image.pack()
        label=("REFERENCE ONLY | approved Mia turnaround" if key=="approved_mia_turnaround"
               else "REFERENCE ONLY | generated draft board")
        empty=bpy.data.objects.new(label,None)
        scene.collection.objects.link(empty); empty.empty_display_type="IMAGE"; empty.data=image
        empty.location=(100,100,0); empty.hide_render=True
        empty["status"]=("approved_visual_reference" if key=="approved_mia_turnaround"
                         else "draft_not_approved")
scene["episode_id"]="S01E01"; scene["scene_id"]="S01_SC01"
scene["asset_status"]="proxy character rejected for visual mismatch; approved Mia turnaround packed for replacement model"
scene["reference_sha256_json"]=json.dumps(ref_meta,sort_keys=True)
scene["audio_policy"]="silent; no voice, music, or subtitles"
scene.frame_set(1)
scene.render.image_settings.file_format="PNG"
scene.render.filepath=os.path.join(out,"preview.png")
bpy.ops.render.render(write_still=True)
review_dir=os.path.join(out,"review_frames")
os.makedirs(review_dir,exist_ok=True)
review_frames=[]
review_frame_numbers=tuple(max(1,round(frame_count*f)) for f in (0.25,0.5,0.75,1.0))
for frame in review_frame_numbers:
    scene.frame_set(frame)
    review_path=os.path.join(review_dir,"review-%04d.png" % frame)
    scene.render.filepath=review_path
    bpy.ops.render.render(write_still=True)
    review_frames.append(review_path)
scene.frame_set(1)
scene.render.filepath=os.path.join(out,"preview.png")
blend=os.path.join(out,"mia_blockout.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend)
video=os.path.join(out,"scene.mp4")
video_status="render_failed"
video_error=None
try:
    scene.render.image_settings.file_format="FFMPEG"
except (TypeError, ValueError):
    ffmpeg=shutil.which("ffmpeg")
    if not ffmpeg:
        video_status="ffmpeg_not_found"
    elif os.path.lexists(video):
        video_status="blocked_existing_video"
    else:
        frame_dir=tempfile.mkdtemp(prefix=".scene-frames-",dir=out)
        partial=os.path.join(out,"scene.partial.mp4")
        try:
            scene.render.image_settings.file_format="PNG"
            scene.render.filepath=os.path.join(frame_dir,"frame_")
            bpy.ops.render.render(animation=True)
            command=[ffmpeg,"-hide_banner","-loglevel","error","-n","-framerate","12",
                     "-start_number","1","-i",os.path.join(frame_dir,"frame_%04d.png"),
                     "-frames:v","720","-c:v","libx264","-pix_fmt","yuv420p",
                     "-movflags","+faststart","-crf","20","-preset","medium","-an",partial]
            proc=subprocess.run(command,capture_output=True,text=True,encoding="utf-8",errors="replace",
                                timeout=900,check=False,shell=False)
            if proc.returncode!=0:
                video_error=(proc.stderr or "")[-1200:]
            elif os.path.isfile(partial) and os.path.getsize(partial)>=1024:
                with open(partial,"rb") as stream: header=stream.read(16)
                if b"ftyp" in header and not os.path.lexists(video):
                    os.replace(partial,video); video_status="exported"
                else:
                    video_status="invalid_or_existing_video"
            else:
                video_status="render_failed"
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
            video_status="ffmpeg_failed"
            video_error=type(exc).__name__
        finally:
            if video_status=="exported":
                shutil.rmtree(frame_dir,ignore_errors=True)
            if os.path.isfile(partial) and video_status!="exported":
                os.remove(partial)
else:
    scene.render.ffmpeg.format="MPEG4"; scene.render.ffmpeg.codec="H264"
    scene.render.ffmpeg.constant_rate_factor="MEDIUM"; scene.render.ffmpeg.video_bitrate=2500
    scene.render.ffmpeg.audio_codec="NONE"
    scene.render.filepath=os.path.join(out,"scene")
    bpy.ops.render.render(animation=True)
    if os.path.isfile(video) and os.path.getsize(video)>=1024:
        video_status="exported"
    else:
        video_status="render_failed"
with open(os.path.join(out,"blender_result.json"),"w",encoding="utf-8") as f:
    json.dump({"status":"completed","stage":"episode1_scene1_animated_animatic",
               "blend_path":blend,"preview_path":os.path.join(out,"preview.png"),
               "review_frame_paths":review_frames,
               "video_path":video if video_status=="exported" else None,
               "video_export_status":video_status,
               "duration_seconds":duration_seconds,"fps":12,"frame_count":frame_count,
               "object_count":len(scene.objects),"audio":"none","subtitles":"none",
               "mia_rig_bones":len(scene.objects["Mia_Rig"].data.bones),
               "stepa_rig_bones":len(scene.objects["Stepa_Rig"].data.bones),
               "asset_provenance":ref_meta,"production_models_available":False,
               "visual_acceptance":"rejected_proxy_mismatch; do not call this render final",
               "manual_visual_review_required":True,"video_error":video_error},f,ensure_ascii=False)
'''


def _agent_cancel_requested(task_id: str | None) -> bool:
    if not task_id:
        return False
    try:
        from local_agent.studio_jobs import agent_task_cancel_requested
        return agent_task_cancel_requested(task_id)
    except (OSError, ValueError, RuntimeError):
        return False

def _terminate_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        taskkill = shutil.which("taskkill.exe")
        if taskkill:
            try:
                subprocess.run([taskkill, "/PID", str(int(process.pid)), "/T", "/F"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=12, check=False, shell=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()
        process.wait()

def _run_cancellable_process(command: list[str], *, cwd: Path, timeout: int,
                             task_id: str | None):
    """Run Blender in its own process group and honor only this task's local cancel signal."""
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    started = time.monotonic()
    with tempfile.TemporaryFile() as stdout_stream, tempfile.TemporaryFile() as stderr_stream:
        try:
            process = subprocess.Popen(
                command, cwd=str(cwd), stdin=subprocess.DEVNULL,
                stdout=stdout_stream, stderr=stderr_stream, shell=False,
                close_fds=True, creationflags=flags, start_new_session=(os.name != "nt"),
            )
        except OSError as exc:
            return None, False, False, "", type(exc).__name__
        cancelled = False
        timed_out = False
        while process.poll() is None:
            if _agent_cancel_requested(task_id):
                cancelled = True
                _terminate_process_tree(process)
                break
            if time.monotonic() - started >= timeout:
                timed_out = True
                _terminate_process_tree(process)
                break
            time.sleep(0.25)
        stdout_stream.flush()
        stderr_stream.flush()
        stdout_stream.seek(max(0, stdout_stream.tell() - 262_144))
        stdout = stdout_stream.read().decode("utf-8", errors="replace")
        stderr_stream.seek(max(0, stderr_stream.tell() - 262_144))
        stderr = stderr_stream.read().decode("utf-8", errors="replace")
        completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        return completed, cancelled, timed_out, "", None

def _render_episode1_release(project: Path, workspace: Path, blender: Path, duration_seconds: int, task_id: str | None = None) -> dict[str, Any]:
    """Render only the fixed Episode 1 scene folder; never overwrite existing files."""
    if project.name != "S01E01_SC01_RELEASE":
        return {"status": "rejected", "reason": "episode1_release_project_not_allowlisted"}
    asset_root = workspace / "episode1" / "assets"
    required = [
        asset_root / "characters" / "passports" / "mia.json",
        asset_root / "characters" / "passports" / "stepa.json",
        asset_root / "references" / "episode-01-reference-board.png",
        asset_root / "references" / "mia_turnaround_approved_20261012.jpeg",
    ]
    guarded = [workspace / "episode1", asset_root, *required]
    if any(is_link_or_junction(p) for p in guarded) or any(not p.is_file() for p in required):
        return {"status": "blocked", "reason": "pinned_episode1_reference_assets_missing"}
    if (project / "scene.mp4").exists():
        return {"status": "blocked", "reason": "release_video_exists_no_overwrite"}
    import tempfile
    with tempfile.TemporaryDirectory(prefix=".mia-release-", dir=project) as temp:
        script = Path(temp) / "episode1_animation.py"
        cfg = Path(temp) / "release.json"
        script.write_text(_episode1_animation_script(), encoding="utf-8")
        cfg.write_text(json.dumps({"output_dir": str(project), "asset_root": str(asset_root),
                                   "duration_seconds": duration_seconds},
                                  ensure_ascii=False), encoding="utf-8")
        try:
            proc, cancelled, timed_out, _, error_type = _run_cancellable_process(
                [str(blender), "--background", "--disable-autoexec", "--offline-mode",
                 "--python-exit-code", "1", "--python", str(script), "--", str(cfg)],
                cwd=project, timeout=2400, task_id=task_id,
            )
        except (OSError, RuntimeError) as exc:
            return {"status": "error", "error_type": type(exc).__name__}
        if error_type:
            return {"status": "error", "error_type": error_type}
        if cancelled:
            (project / "scene.partial.mp4").unlink(missing_ok=True)
            (project / "scene.mp4").unlink(missing_ok=True)
            for temporary_frames in project.glob(".scene-frames-*"):
                if temporary_frames.is_dir() and not is_link_or_junction(temporary_frames):
                    shutil.rmtree(temporary_frames, ignore_errors=True)
            return {"status": "cancelled", "reason": "cancelled_by_user", "task_id": task_id}
        if timed_out:
            return {"status": "timeout", "reason": "episode1_animation_render_timeout"}
    if proc.returncode != 0:
        return {"status": "failed", "reason": "episode1_animation_render_failed",
                "return_code": proc.returncode, "stderr_tail": (proc.stderr or "")[-2500:]}
    manifest = project / "blender_result.json"
    blend = project / "mia_blockout.blend"
    preview = project / "preview.png"
    video = project / "scene.mp4"
    if any(is_link_or_junction(p) or not p.is_file() or p.stat().st_size == 0
           for p in (manifest, blend, preview)):
        return {"status": "failed", "reason": "episode1_release_output_missing"}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "failed", "reason": "episode1_release_manifest_invalid"}
    png_ok, png_reason, dimensions = _validate_png(preview, (720, 1280))
    if not png_ok:
        return {"status": "failed", "reason": png_reason}
    if (data.get("status") != "completed" or data.get("stage") != "episode1_scene1_animated_animatic"
            or data.get("duration_seconds") != duration_seconds or data.get("frame_count") != duration_seconds * 12
            or data.get("audio") != "none" or data.get("subtitles") != "none"
            or data.get("mia_rig_bones",0) < 20 or data.get("stepa_rig_bones",0) < 20):
        return {"status": "failed", "reason": "episode1_release_manifest_validation_failed"}
    if data.get("video_export_status") == "exported":
        if is_link_or_junction(video) or not video.is_file() or video.stat().st_size < 1024:
            return {"status": "failed", "reason": "episode1_release_video_missing"}
        with video.open("rb") as stream: header = stream.read(16)
        if b"ftyp" not in header or video.stat().st_size > 32_000_000:
            return {"status": "failed", "reason": "episode1_release_video_invalid_or_too_large"}
    else:
        return {"status": "failed", "reason": "episode1_video_export_" + str(data.get("video_export_status", "status_missing"))}
    review_frames = data.get("review_frame_paths", [])
    expected_review_names = {f"review-{round(duration_seconds * 12 * part):04d}.png" for part in (0.25, 0.5, 0.75, 1.0)}
    if not isinstance(review_frames, list) or {Path(p).name for p in review_frames} != expected_review_names:
        return {"status": "failed", "reason": "episode1_review_frame_manifest_invalid"}
    for frame_path in review_frames:
        ok, reason, _ = _validate_png(Path(frame_path), (720, 1280))
        if not ok:
            return {"status": "failed", "reason": "episode1_review_frame_" + reason}
    return {"status": "completed", "task": "blender_mia_blockout",
            "stage": data["stage"], "project_dir": str(project),
            "production_ready": False,
            "visual_acceptance": data.get("visual_acceptance", "rejected_proxy_mismatch"),
            "character_model_kind": "segmented_proxy",
            "blend_path": str(blend), "preview_path": str(preview),
            "video_path": str(video) if data.get("video_export_status") == "exported" else None,
            "video_export_status": data.get("video_export_status"),
            "review_frames": review_frames, "resolution": dimensions,
            "duration_seconds": duration_seconds, "fps": 12, "frame_count": duration_seconds * 12,
            "object_count": data.get("object_count"), "mia_rig_bones": data.get("mia_rig_bones"),
            "stepa_rig_bones": data.get("stepa_rig_bones"), "manual_review_required": True,
            "note": "Animated courtyard animatic with 20-control segmented proxy rigs; smooth production skinning and final model approval remain outstanding."}


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


def create_mia_blockout(project_name: str, *, overwrite: bool = False, duration_seconds: int = 5, task_id: str | None = None) -> dict[str, Any]:
    """Create a fixed Mia character/prop blockout, save .blend, and validate preview."""
    if not isinstance(project_name, str) or not project_name or len(project_name) > 48:
        raise BlenderWorkflowError("Invalid project name.")
    if type(duration_seconds) is not int or duration_seconds not in (5, 60):
        raise BlenderWorkflowError("Episode 1 duration must be 5 seconds for review or 60 seconds after review.")
    if project_name == "MIA_REFERENCE_REVIEW":
        if overwrite or duration_seconds != 5:
            raise BlenderWorkflowError("Character review creates a fresh static version, without overwrite.")
        return create_reference_mia_model(task_id=task_id)
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
    if project_name == "S01E01_SC01_RELEASE":
        outputs.extend([project / "preview.png", project / "scene.mp4"])
    if any(is_link_or_junction(p) for p in outputs + [project / "blender_stdout.log", project / "blender_stderr.log"]):
        raise BlenderWorkflowError("Output files must not be symlinks or junctions.")
    if (project_name == "S01E01_SC01_RELEASE"
            and all(p.is_file() for p in outputs[:3])
            and not (project / "scene.mp4").exists()
            and not overwrite):
        # A preview may exist from a prior animation attempt that failed during
        # video setup. The source blockout remains valid and can be animated in place.
        return _render_episode1_release(project, workspace, blender, duration_seconds, task_id)
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
            proc, cancelled, timed_out, _, error_type = _run_cancellable_process(
                [str(blender), "--background", "--factory-startup", "--disable-autoexec", "--python-exit-code", "1",
                 "--python", str(script), "--", str(cfg)],
                cwd=project, timeout=1200, task_id=task_id,
            )
            if error_type:
                return {"status": "error", "error_type": error_type}
            if cancelled:
                return {"status": "cancelled", "reason": "cancelled_by_user", "task_id": task_id,
                        "project_dir": str(project)}
            if timed_out:
                return {"status": "timeout", "reason": "blender_blockout_timeout", "project_dir": str(project)}
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
        if not isinstance(data, dict) or data.get("status") != "completed" or data.get("stage") != "episode1_scene1_blockout" or data.get("proxy_rig_count") != 3 or data.get("bound_mesh_count", 0) < 30:
            return {"status": "failed", "reason": "output_manifest_validation_failed", "project_dir": str(project)}
        return {"status": "completed", "task": "blender_mia_blockout", "stage": "episode1_scene1_blockout",
                "project_dir": str(project), "blend_path": str(blend), "preview_path": str(preview),
                "resolution": dimensions, "object_count": data.get("object_count"),
                "proxy_rig_count": data.get("proxy_rig_count"), "bound_mesh_count": data.get("bound_mesh_count"),
                "engine": data.get("engine"), "manual_review_required": True,
                "note": "Episode 1 opening-scene proxy set with rigid placeholder rigs; visual review required."}

    completed = False
    try:
        result = generate()
        if result.get("status") == "completed" and project_name == "S01E01_SC01_RELEASE":
            result = _render_episode1_release(project, workspace, blender, duration_seconds, task_id)
        completed = result.get("status") == "completed"
        return result
    finally:
        if result.get("status") == "cancelled" and backup_dir is None:
            for path in outputs:
                if path.is_file() and not is_link_or_junction(path):
                    path.unlink(missing_ok=True)
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


def create_reference_mia_model(*, task_id: str | None = None) -> dict[str, Any]:
    """Build a separate real-mesh character review, preserving all scene versions."""
    import base64
    import hashlib
    import re
    from datetime import datetime, timezone
    ident = task_id or datetime.now(timezone.utc).strftime("local-review-%Y%m%dT%H%M%SZ")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", ident):
        raise BlenderWorkflowError("Invalid character review identity")
    value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    blender = find_blender_executable()
    if not value or blender is None or not blender.is_file():
        return {"status": "blocked", "reason": "local_workspace_or_blender_missing"}
    workspace = Path(value).expanduser().resolve()
    reference = workspace / "episode1" / "assets" / "references" / "mia_turnaround_approved_20261012.jpeg"
    if any(is_link_or_junction(p) for p in [reference, *reference.parents][:5]) or not reference.is_file():
        return {"status": "blocked", "reason": "approved_mia_reference_missing"}
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    if digest != "7a3194accfecdb4873bc7d4cd8015edb5a94075ca05c72013c5ad97b4a32e383":
        return {"status": "blocked", "reason": "approved_mia_reference_digest_mismatch"}
    root = workspace / "MIA_REFERENCE_REVIEW"
    out = root / ident
    if is_link_or_junction(root) or is_link_or_junction(out) or out.exists():
        return {"status": "blocked", "reason": "character_review_output_exists_or_unsafe"}
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix=".model-build-", dir=out) as temporary:
        script = Path(temporary) / "mia_model.py"
        config = Path(temporary) / "model.json"
        script.write_text(_mia_reference_model_script(), encoding="utf-8")
        config.write_text(json.dumps({"output_dir": str(out), "reference_path": str(reference)}), encoding="utf-8")
        proc, cancelled, timed_out, _, error = _run_cancellable_process(
            [str(blender), "--background", "--factory-startup", "--disable-autoexec", "--offline-mode",
             "--python-exit-code", "1", "--python", str(script), "--", str(config)],
            cwd=out, timeout=1500, task_id=task_id)
    if error:
        return {"status": "error", "error_type": error}
    (out / "blender_stdout.log").write_text((proc.stdout or "")[-262144:], encoding="utf-8")
    (out / "blender_stderr.log").write_text((proc.stderr or "")[-262144:], encoding="utf-8")
    if cancelled or timed_out:
        return {"status": "cancelled" if cancelled else "timeout", "project_dir": str(out)}
    if proc.returncode:
        return {"status": "failed", "reason": "mia_model_build_failed", "return_code": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-2500:], "project_dir": str(out)}
    result_file = out / "model_result.json"
    if not result_file.is_file() or is_link_or_junction(result_file) or result_file.stat().st_size > 20000:
        return {"status": "failed", "reason": "model_manifest_missing"}
    data = json.loads(result_file.read_text("utf-8"))
    blend = out / "mia_reference_model.blend"
    if not blend.is_file() or is_link_or_junction(blend) or blend.stat().st_size == 0:
        return {"status": "failed", "reason": "model_blend_missing"}
    previews = {}
    for view in ("front", "side", "back", "three_quarter"):
        path = out / (view + ".png")
        if is_link_or_junction(path) or not path.is_file():
            return {"status": "failed", "reason": "model_view_missing_" + view}
        ok, reason, dimensions = _validate_png(path, (600, 900))
        if not ok:
            return {"status": "failed", "reason": "model_preview_invalid_" + reason}
        previews[view] = str(path)
    thumbs = {}
    for view in ("front", "side", "back", "face"):
        path = out / (view + "_thumb.jpg")
        if path.is_file() and not is_link_or_junction(path) and path.stat().st_size <= 10000:
            raw = path.read_bytes()
            if raw.startswith(b"\xff\xd8"):
                thumbs[view] = base64.b64encode(raw).decode("ascii")
    delivery = {"status": "not_exported"}
    try:
        from local_agent.dropbox_review import read_settings, discover_dropbox_root, ReviewDeliveryError
        if read_settings()["enabled"]:
            sync = discover_dropbox_root()
            if sync is not None:
                destination = sync / "AI-Agent-Reviews" / "MIA_REFERENCE_REVIEW" / ident
                for candidate in (destination, destination.parent, destination.parent.parent):
                    if is_link_or_junction(candidate):
                        raise ReviewDeliveryError("Unsafe model review export directory")
                if destination.exists():
                    raise ReviewDeliveryError("Model review export version already exists")
                destination.mkdir(parents=True)
                for view in previews:
                    shutil.copy2(out / (view + ".png"), destination / (view + ".png"))
                face = out / "face_thumb.jpg"
                if face.is_file() and not is_link_or_junction(face):
                    shutil.copy2(face, destination / "face_thumb.jpg")
                shutil.copy2(result_file, destination / "model_result.json")
                delivery = {"status": "copied_to_local_sync_folder", "relative_folder": "AI-Agent-Reviews/MIA_REFERENCE_REVIEW/" + ident,
                            "remote_sync_verified": False}
    except (OSError, ValueError, RuntimeError):
        delivery = {"status": "export_failed_model_preserved"}
    return {"status": "completed", "stage": "mia_reference_model_review",
            "project_dir": str(out), "blend_path": str(blend), "preview_paths": previews,
            "thumbnail_jpeg_base64": thumbs, "reference_sha256": digest,
            "mesh_count": data.get("mesh_count"), "vertex_count": data.get("vertex_count"),
            "production_ready": False, "visual_acceptance": "pending_comparison_with_approved_reference",
            "rig_status": "not_rigged_for_visual_review", "animation_rendered": False,
            "review_delivery": delivery}







def create_mia_astra_pass_one(*, task_id: str | None = None) -> dict[str, Any]:
    """Create a NEW version of Mia's real mesh with only controlled, reversible edits.

    Astra supplied a human-reviewable critique; it does NOT supply executable
    Python, commands, files or arbitrary transforms. The original V6 .blend
    remains unchanged. Changes are fixed and limited to confirmed problem areas.
    """
    import re
    import hashlib
    import base64
    from datetime import datetime, timezone
    ident = task_id or datetime.now(timezone.utc).strftime("mia-pass1-%Y%m%dT%H%M%SZ")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", ident):
        return {"status": "blocked", "reason": "invalid_version_id"}
    value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    blender = find_blender_executable()
    if not value or blender is None or not blender.is_file():
        return {"status": "blocked", "reason": "local_workspace_or_blender_missing"}
    base = Path(value).expanduser().resolve()
    root = base / "MIA_REFERENCE_REVIEW"
    source = root / "mia-static-model-v6-20261012T222818971Z"
    model = source / "mia_reference_model.blend"
    ref = base / "episode1/assets/references/mia_turnaround_approved_20261012.jpeg"
    out = root / ident
    for item in (root, source, model, ref, out):
        if is_link_or_junction(item):
            return {"status": "blocked", "reason": "unsafe_model_path"}
    if (out.exists() or not model.is_file() or model.stat().st_size < 1000
            or not ref.is_file() or hashlib.sha256(ref.read_bytes()).hexdigest() !=
            "7a3194accfecdb4873bc7d4cd8015edb5a94075ca05c72013c5ad97b4a32e383"):
        return {"status": "blocked", "reason": "source_missing_reference_invalid_or_version_exists"}
    # Requiring Astra's actual six-image review gates this controlled correction.
    approved_review = source / "astra_identity_review.txt"
    if is_link_or_junction(approved_review) or not approved_review.is_file():
        return {"status": "blocked", "reason": "astra_visual_review_missing"}
    review_text = approved_review.read_text(encoding="utf-8")
    if not 100 < len(review_text) < 20000 or "REJECT" not in review_text:
        return {"status": "blocked", "reason": "astra_rejection_not_verified"}
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix=".mia-astra-pass1-", dir=out) as temp:
        script = Path(temp) / "apply_fixed_pass.py"
        config = Path(temp) / "config.json"
        script.write_text(_mia_astra_pass1_script(), encoding="utf-8")
        config.write_text(json.dumps({"output": str(out),
                                      "parent_blend": str(model)}), encoding="utf-8")
        proc, cancelled, timed_out, _, error = _run_cancellable_process(
            [str(blender), "--background", str(model), "--disable-autoexec",
             "--offline-mode", "--python-exit-code", "1",
             "--python", str(script), "--", str(config)],
            cwd=out, timeout=1500, task_id=task_id)
    if error:
        return {"status": "error", "error_type": error, "version_dir": str(out)}
    (out / "blender_stdout.log").write_text((proc.stdout or "")[-131072:], encoding="utf-8")
    (out / "blender_stderr.log").write_text((proc.stderr or "")[-131072:], encoding="utf-8")
    if cancelled or timed_out:
        return {"status": "cancelled" if cancelled else "timeout", "version_dir": str(out)}
    if proc.returncode:
        return {"status": "failed", "reason": "fixed_pass_blender_error",
                "return_code": proc.returncode,
                "error_tail": (proc.stderr or "")[-1600:], "version_dir": str(out)}
    new_blend = out / "mia_reference_model.blend"
    stats_path = out / "model_result.json"
    if (not new_blend.is_file() or new_blend.stat().st_size < 1000
            or not stats_path.is_file() or is_link_or_junction(stats_path)):
        return {"status": "failed", "reason": "corrected_model_or_manifest_missing"}
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if not stats.get("correction_counts") or sum(stats["correction_counts"].values()) == 0:
        return {"status": "failed", "reason": "no_geometry_or_material_modifications_applied"}
    previews = {}
    for view in ("front", "three_quarter", "side", "back"):
        img = out / (view + ".png")
        if is_link_or_junction(img) or not img.is_file():
            return {"status": "failed", "reason": "corrected_view_missing_" + view}
        ok, reason, _ = _validate_png(img, (600, 900))
        if not ok:
            return {"status": "failed", "reason": "corrected_view_invalid_" + reason}
        previews[view] = str(img)
    thumbs = {}
    for view in ("front", "side", "back", "face"):
        img = out / (view + "_thumb.jpg")
        if img.is_file() and not is_link_or_junction(img) and img.stat().st_size <= 11000:
            raw = img.read_bytes()
            if raw.startswith(b"\xff\xd8"):
                thumbs[view] = base64.b64encode(raw).decode("ascii")
    return {"status": "completed", "stage": "mia_astra_fixed_pass_one",
            "parent": str(model), "blend_path": str(new_blend),
            "project_dir": str(out), "preview_paths": previews,
            "thumbnail_jpeg_base64": thumbs,
            "correction_counts": stats["correction_counts"],
            "visual_acceptance": "pending_comparison_to_approved_mia",
            "source_preserved": True, "production_ready": False,
            "animation_rendered": False, "rig_added": False}


def _mia_astra_pass1_script() -> str:
    """Bundled fixed Blender correction script; never obtained from OctavAPI."""
    return r'''import bpy
import json
import os
import sys
from mathutils import Vector

config = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
out = config["output"]
scene = bpy.context.scene
changes = {"trouser_materials":0, "backpack_materials":0,
           "low_bun_meshes":0, "front_flyaway_visibility":0}
# Do NOT alter head, eyes, facial landmarks, body proportions or video settings.
for ob in bpy.data.objects:
    if ob.type != "MESH":
        continue
    n = ob.name.lower()
    # Remove strong projected/baked patches where Astra flagged trouser
    # artifacts. Keep all original folds, pockets and the actual geometry.
    if ("trouser" in n or "cargo" in n or "leg_outer" in n):
        if ob.data.materials:
            mat = ob.data.materials[0].copy()
            if mat.use_nodes:
                base = mat.node_tree.nodes.get("Principled BSDF")
                if base:
                    target = base.inputs["Base Color"]
                    for link in list(target.links):
                        mat.node_tree.links.remove(link)
                    target.default_value = (0.29, 0.16, 0.09, 1.0)
                    base.inputs["Roughness"].default_value = 0.82
            ob.data.materials[0] = mat
            changes["trouser_materials"] += 1
    # Explicitly target backpack body only, leaving belt buckles, shoulder
    # straps and original geometry unchanged in the first pass.
    if "backpack" in n and not any(x in n for x in ("strap","buckle","zipper","hardware")):
        if ob.data.materials:
            mat = ob.data.materials[0].copy()
            if mat.use_nodes:
                bsdf = mat.node_tree.nodes.get("Principled BSDF")
                if bsdf:
                    base = bsdf.inputs["Base Color"]
                    for link in list(base.links):
                        mat.node_tree.links.remove(link)
                    base.default_value = (0.48, 0.32, 0.095, 1.0)
                    bsdf.inputs["Roughness"].default_value = 0.79
            ob.data.materials[0] = mat
            changes["backpack_materials"] += 1
    # Soften excessively tall, regular bun geometry without changing its
    # centroid, as requested in Astra's comparative review.
    if n.startswith(("low_bun_core","loose_bun_loop","bun_fine_fiber")):
        for vertex in ob.data.vertices:
            vertex.co.z = 3.26 + (vertex.co.z - 3.26) * 0.84
        ob.data.update()
        changes["low_bun_meshes"] += 1
    # Minimize overly dense vertical fringe fibres. These are detailed
    # accessory meshes, NOT the primary side-parted scalp geometry.
    if n.startswith("fringe_fine_fiber"):
        suffix = "".join(ch for ch in n if ch.isdigit())
        if suffix and int(suffix) % 3 == 0:
            ob.hide_render = True
            changes["front_flyaway_visibility"] += 1

if not changes["trouser_materials"] or not changes["low_bun_meshes"]:
    raise RuntimeError("Required correction mesh groups not found; refuse silent no-op")

scene["identity_status"] = "UNAPPROVED_STATIC_MIA_PASS_1"
scene["parent_model"] = config["parent_blend"]
scene["edits"] = json.dumps(changes, sort_keys=True)
# Save a DIFFERENT version, never overwrite parent.
blend = os.path.join(out, "mia_reference_model.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend)
cam = scene.camera
if not cam:
    raise RuntimeError("Review camera missing")
cam.data.type = "ORTHO"
cam.data.ortho_scale = 4.10
scene.render.resolution_x = 600
scene.render.resolution_y = 900
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"

def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()

views = (("front",(0,-8,2.30)),("three_quarter",(5.5,-7,2.45)),
         ("side",(8,0,2.30)),("back",(0,8,2.30)))
for name, pos in views:
    cam.location = pos
    aim(cam, (0,0,1.87))
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = os.path.join(out, name + ".png")
    bpy.ops.render.render(write_still=True)
    if name in ("front","side","back"):
        photo = bpy.data.images.load(scene.render.filepath, check_existing=False)
        photo.scale(160, 240)
        look = (scene.view_settings.view_transform, scene.view_settings.look,
                scene.view_settings.exposure, scene.view_settings.gamma)
        try:
            scene.view_settings.view_transform = "Standard"
            scene.view_settings.look = "None"
            scene.view_settings.exposure = 0
            scene.view_settings.gamma = 1
            scene.render.image_settings.file_format = "JPEG"
            scene.render.image_settings.quality = 60
            photo.save_render(os.path.join(out, name + "_thumb.jpg"), scene=scene)
        finally:
            scene.view_settings.view_transform, scene.view_settings.look = look[0:2]
            scene.view_settings.exposure, scene.view_settings.gamma = look[2:4]
            bpy.data.images.remove(photo)
# A separate facial close-up makes review without video possible.
cam.data.ortho_scale = 1.45
cam.location = (.70,-7,3.20)
aim(cam,(0,-.04,3.12))
scene.render.resolution_x = 256
scene.render.resolution_y = 256
scene.render.image_settings.file_format = "JPEG"
scene.render.image_settings.quality = 55
scene.render.filepath = os.path.join(out, "face_thumb.jpg")
bpy.ops.render.render(write_still=True)
with open(os.path.join(out, "model_result.json"), "w", encoding="utf-8") as sink:
    json.dump({"correction_counts":changes,
               "parent_model":config["parent_blend"],"new_blend":blend,
               "video_rendered":False,"visual_acceptance":"pending"},
              sink, ensure_ascii=False, indent=2)
'''



def create_mia_identity_shape_pass_two(*, task_id: str | None = None) -> dict[str, Any]:
    """Create a new static Mia 3D look-dev checkpoint focused on FACE SHAPE.

    A fixed reviewed Blender script modifies eye assemblies, a small jaw contour,
    and the side fringe on ONE previously saved 3D mesh. It does not regenerate
    Mia, touch animations, run cloud code, or overwrite earlier versions.
    """
    import base64
    import hashlib
    import re
    from datetime import datetime, timezone
    ident = task_id or datetime.now(timezone.utc).strftime("mia-face-pass2-%Y%m%dT%H%M%SZ")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", ident):
        return {"status": "blocked", "reason": "invalid_review_identifier"}
    env = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    blender = find_blender_executable()
    if not env or blender is None or not blender.is_file():
        return {"status": "blocked", "reason": "workspace_or_blender_unavailable"}
    workspace = Path(env).expanduser().resolve()
    root = workspace / "MIA_REFERENCE_REVIEW"
    parent = root / "mia-astra-pass1-20261012T225028721Z"
    source = parent / "mia_reference_model.blend"
    previous_summary = parent / "model_result.json"
    canonical = workspace / "episode1" / "assets" / "references" / "mia_turnaround_approved_20261012.jpeg"
    output = root / ident
    for entry in (root, parent, source, previous_summary, canonical, output):
        if is_link_or_junction(entry):
            return {"status": "blocked", "reason": "unsafe_symbolic_path"}
    if (output.exists() or not source.is_file() or not previous_summary.is_file()
            or source.stat().st_size < 1000 or not canonical.is_file()):
        return {"status": "blocked", "reason": "prior_approved_checkpoint_missing_or_output_exists"}
    if hashlib.sha256(canonical.read_bytes()).hexdigest() != (
            "7a3194accfecdb4873bc7d4cd8015edb5a94075ca05c72013c5ad97b4a32e383"):
        return {"status": "blocked", "reason": "approved_mia_reference_hash_mismatch"}
    summary = json.loads(previous_summary.read_text(encoding="utf-8"))
    if not summary.get("correction_counts") or summary.get("video_rendered") is not False:
        return {"status": "blocked", "reason": "parent_not_safe_static_checkpoint"}
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix=".face-review-", dir=output) as temp:
        script = Path(temp) / "apply_face_identity.py"
        conf = Path(temp) / "config.json"
        script.write_text(_mia_identity_shape_pass_two_script(), encoding="utf-8")
        conf.write_text(json.dumps({"output": str(output), "parent_blend": str(source)}), encoding="utf-8")
        proc, cancelled, timed_out, _, error = _run_cancellable_process(
            [str(blender), "--background", str(source), "--disable-autoexec",
             "--offline-mode", "--python-exit-code", "1",
             "--python", str(script), "--", str(conf)],
            cwd=output, timeout=1500, task_id=task_id)
    if error:
        return {"status": "error", "reason": error, "project_dir": str(output)}
    (output / "blender_stdout.log").write_text((proc.stdout or "")[-131072:], encoding="utf-8")
    (output / "blender_stderr.log").write_text((proc.stderr or "")[-131072:], encoding="utf-8")
    if cancelled or timed_out:
        return {"status": "cancelled" if cancelled else "timeout", "project_dir": str(output)}
    if proc.returncode:
        return {"status": "failed", "reason": "fixed_face_blender_pass_failed",
                "return_code": proc.returncode,
                "error_tail": (proc.stderr or "")[-1500:], "project_dir": str(output)}
    model = output / "mia_reference_model.blend"
    manifest = output / "model_result.json"
    if (not model.is_file() or model.stat().st_size < 1000
            or not manifest.is_file() or is_link_or_junction(manifest)):
        return {"status": "failed", "reason": "edited_blend_or_manifest_missing"}
    data = json.loads(manifest.read_text(encoding="utf-8"))
    counts = data.get("correction_counts", {})
    if not counts.get("eye_mesh_groups") or not counts.get("jaw_vertices") or not counts.get("side_fringe_mesh_groups"):
        return {"status": "failed", "reason": "required_mesh_edits_not_confirmed",
                "counts": counts}
    previews = {}
    for view in ("front", "three_quarter", "side", "back"):
        frame = output / (view + ".png")
        if is_link_or_junction(frame) or not frame.is_file():
            return {"status": "failed", "reason": "missing_" + view}
        ok, reason, _ = _validate_png(frame, (600, 900))
        if not ok:
            return {"status": "failed", "reason": view + "_" + reason}
        previews[view] = str(frame)
    thumbs = {}
    for view in ("front", "side", "back", "face"):
        pic = output / (view + "_thumb.jpg")
        if pic.is_file() and not is_link_or_junction(pic) and pic.stat().st_size <= 11000:
            raw = pic.read_bytes()
            if raw.startswith(b"\xff\xd8"):
                thumbs[view] = base64.b64encode(raw).decode("ascii")
    return {"status": "completed", "stage": "mia_static_identity_shape_pass_two",
            "blend_path": str(model), "project_dir": str(output),
            "parent_blend": str(source), "preview_paths": previews,
            "thumbnail_jpeg_base64": thumbs, "correction_counts": counts,
            "reference_sha256": hashlib.sha256(canonical.read_bytes()).hexdigest(),
            "source_preserved": True, "production_ready": False,
            "visual_acceptance": "awaiting_visual_comparison",
            "rig_added": False, "animation_rendered": False}


def _mia_identity_shape_pass_two_script() -> str:
    """Deterministic Blender script for *actual* face & hairstyle mesh vertices."""
    return r'''import bpy, json, os, sys, math
from mathutils import Vector
data = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
out = data["output"]
scene = bpy.context.scene
counts = {"eye_mesh_groups": 0, "eye_vertices": 0,
          "jaw_vertices": 0, "side_fringe_mesh_groups": 0,
          "side_fringe_vertices": 0}
# Both eyes, eyelids, eyelashes, iris detail and catchlights share one focal
# coordinate per side. Scale the COMPLETE assembly consistently; do not leave
# huge disconnected sclera or eyebrows behind. This is an editable 3D change.
eye_groups = ("eye_", "iris_fleck", "lid_skin_transition", "upper_eyelid",
              "lower_eyelid", "fine_upper_lash_line", "outer_lash")
for ob in bpy.data.objects:
    if ob.type != "MESH" or not ob.data.vertices:
        continue
    n = ob.name.lower()
    if n.startswith(eye_groups):
        centroid = sum(v.co.x for v in ob.data.vertices) / len(ob.data.vertices)
        eye_x = 0.217 if centroid >= 0 else -0.217
        for v in ob.data.vertices:
            v.co.x = eye_x + (v.co.x - eye_x) * 0.915
            v.co.z = 3.43 + (v.co.z - 3.43) * 0.935
            v.co.y = -0.35 + (v.co.y + 0.35) * 0.985
            counts["eye_vertices"] += 1
        ob.data.update()
        counts["eye_mesh_groups"] += 1
    elif n == "mia_sculpted_head":
        for v in ob.data.vertices:
            z = v.co.z
            # Smooth bell-shaped narrowing of lower cheek and chin area only.
            # Do not modify the forehead, nose length or head height.
            f = math.exp(-((z - 3.20) / 0.19) ** 2)
            v.co.x *= (1.0 - 0.043 * f)
            counts["jaw_vertices"] += 1
        ob.data.update()
    elif n.startswith("side_swept_fringe_"):
        for v in ob.data.vertices:
            # Favor the reference's side-swept flow rather than vertical bangs.
            t = max(0.0, min(1.0, (3.97 - v.co.z) / 0.35))
            v.co.x -= 0.032 * t
            v.co.y -= 0.006 * t
            counts["side_fringe_vertices"] += 1
        ob.data.update()
        counts["side_fringe_mesh_groups"] += 1

if (counts["eye_mesh_groups"] < 10 or counts["jaw_vertices"] < 1000
        or counts["side_fringe_mesh_groups"] < 3):
    raise RuntimeError("Expected Mia face/head/side-swept meshes absent")
scene["identity_status"] = "UNAPPROVED_MIA_SHAPE_PASS_2"
scene["parent_model"] = data["parent_blend"]
scene["mesh_corrections"] = json.dumps(counts, sort_keys=True)
blend = os.path.join(out, "mia_reference_model.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend)
camera = scene.camera
if camera is None:
    raise RuntimeError("Fixed review camera missing")
camera.data.type = "ORTHO"
camera.data.ortho_scale = 4.10
scene.render.resolution_percentage = 100
scene.render.resolution_x = 600
scene.render.resolution_y = 900
scene.render.image_settings.file_format = "PNG"

def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
views = (("front", (0,-8,2.30)), ("three_quarter", (5.5,-7,2.45)),
         ("side", (8,0,2.30)), ("back", (0,8,2.30)))
for name, location in views:
    camera.location = location
    aim(camera, (0,0,1.87))
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = os.path.join(out, name + ".png")
    bpy.ops.render.render(write_still=True)
    if name in ("front", "side", "back"):
        pic = bpy.data.images.load(scene.render.filepath, check_existing=False)
        pic.scale(160, 240)
        previous = (scene.view_settings.view_transform, scene.view_settings.look,
                    scene.view_settings.exposure, scene.view_settings.gamma)
        try:
            scene.view_settings.view_transform = "Standard"
            scene.view_settings.look = "None"
            scene.view_settings.exposure = 0
            scene.view_settings.gamma = 1
            scene.render.image_settings.file_format = "JPEG"
            scene.render.image_settings.quality = 60
            pic.save_render(os.path.join(out, name + "_thumb.jpg"), scene=scene)
        finally:
            scene.view_settings.view_transform = previous[0]
            scene.view_settings.look = previous[1]
            scene.view_settings.exposure = previous[2]
            scene.view_settings.gamma = previous[3]
            bpy.data.images.remove(pic)
camera.data.ortho_scale = 1.45
camera.location = (.70,-7,3.20)
aim(camera, (0,-.04,3.12))
scene.render.resolution_x = 256
scene.render.resolution_y = 256
scene.render.image_settings.file_format = "JPEG"
scene.render.image_settings.quality = 55
scene.render.filepath = os.path.join(out, "face_thumb.jpg")
bpy.ops.render.render(write_still=True)
with open(os.path.join(out, "model_result.json"), "w", encoding="utf-8") as f:
    json.dump({"correction_counts": counts, "source_model": data["parent_blend"],
               "video_rendered": False, "visual_approval": False,
               "geometry_modified": True},
              f, ensure_ascii=False, indent=2)
'''



def create_mia_hair_identity_pass_three(*, task_id: str | None = None) -> dict[str, Any]:
    """Create a new static 3D Mia hair-shape reconstruction candidate.

    A fixed reviewed Blender script modifies only hair meshes and hair materials
    on ONE previously saved 3D mesh. It does not regenerate
    Mia, touch animations, run cloud code, or overwrite earlier versions.
    """
    import base64
    import hashlib
    import re
    from datetime import datetime, timezone
    ident = task_id or datetime.now(timezone.utc).strftime("mia-face-pass2-%Y%m%dT%H%M%SZ")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", ident):
        return {"status": "blocked", "reason": "invalid_review_identifier"}
    env = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    blender = find_blender_executable()
    if not env or blender is None or not blender.is_file():
        return {"status": "blocked", "reason": "workspace_or_blender_unavailable"}
    workspace = Path(env).expanduser().resolve()
    root = workspace / "MIA_REFERENCE_REVIEW"
    parent = root / "mia-identity-shape-v2-20261012T230037560Z"
    source = parent / "mia_reference_model.blend"
    previous_summary = parent / "model_result.json"
    canonical = workspace / "episode1" / "assets" / "references" / "mia_turnaround_approved_20261012.jpeg"
    output = root / ident
    for entry in (root, parent, source, previous_summary, canonical, output):
        if is_link_or_junction(entry):
            return {"status": "blocked", "reason": "unsafe_symbolic_path"}
    if (output.exists() or not source.is_file() or not previous_summary.is_file()
            or source.stat().st_size < 1000 or not canonical.is_file()):
        return {"status": "blocked", "reason": "prior_approved_checkpoint_missing_or_output_exists"}
    if hashlib.sha256(canonical.read_bytes()).hexdigest() != (
            "7a3194accfecdb4873bc7d4cd8015edb5a94075ca05c72013c5ad97b4a32e383"):
        return {"status": "blocked", "reason": "approved_mia_reference_hash_mismatch"}
    summary = json.loads(previous_summary.read_text(encoding="utf-8"))
    if not summary.get("correction_counts") or summary.get("video_rendered") is not False:
        return {"status": "blocked", "reason": "parent_not_safe_static_checkpoint"}
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix=".face-review-", dir=output) as temp:
        script = Path(temp) / "apply_face_identity.py"
        conf = Path(temp) / "config.json"
        script.write_text(_mia_hair_identity_pass_three_script(), encoding="utf-8")
        conf.write_text(json.dumps({"output": str(output), "parent_blend": str(source)}), encoding="utf-8")
        proc, cancelled, timed_out, _, error = _run_cancellable_process(
            [str(blender), "--background", str(source), "--disable-autoexec",
             "--offline-mode", "--python-exit-code", "1",
             "--python", str(script), "--", str(conf)],
            cwd=output, timeout=1500, task_id=task_id)
    if error:
        return {"status": "error", "reason": error, "project_dir": str(output)}
    (output / "blender_stdout.log").write_text((proc.stdout or "")[-131072:], encoding="utf-8")
    (output / "blender_stderr.log").write_text((proc.stderr or "")[-131072:], encoding="utf-8")
    if cancelled or timed_out:
        return {"status": "cancelled" if cancelled else "timeout", "project_dir": str(output)}
    if proc.returncode:
        return {"status": "failed", "reason": "fixed_face_blender_pass_failed",
                "return_code": proc.returncode,
                "error_tail": (proc.stderr or "")[-1500:], "project_dir": str(output)}
    model = output / "mia_reference_model.blend"
    manifest = output / "model_result.json"
    if (not model.is_file() or model.stat().st_size < 1000
            or not manifest.is_file() or is_link_or_junction(manifest)):
        return {"status": "failed", "reason": "edited_blend_or_manifest_missing"}
    data = json.loads(manifest.read_text(encoding="utf-8"))
    counts = data.get("correction_counts", {})
    if not counts.get("back_locks_softened") or not counts.get("crown_fibers_hidden") or not counts.get("swept_fringe_groups"):
        return {"status": "failed", "reason": "required_hair_mesh_edits_not_confirmed",
                "counts": counts}
    previews = {}
    for view in ("front", "three_quarter", "side", "back"):
        frame = output / (view + ".png")
        if is_link_or_junction(frame) or not frame.is_file():
            return {"status": "failed", "reason": "missing_" + view}
        ok, reason, _ = _validate_png(frame, (600, 900))
        if not ok:
            return {"status": "failed", "reason": view + "_" + reason}
        previews[view] = str(frame)
    thumbs = {}
    for view in ("front", "side", "back", "face"):
        pic = output / (view + "_thumb.jpg")
        if pic.is_file() and not is_link_or_junction(pic) and pic.stat().st_size <= 11000:
            raw = pic.read_bytes()
            if raw.startswith(b"\xff\xd8"):
                thumbs[view] = base64.b64encode(raw).decode("ascii")
    return {"status": "completed", "stage": "mia_static_hair_identity_pass_three",
            "blend_path": str(model), "project_dir": str(output),
            "parent_blend": str(source), "preview_paths": previews,
            "thumbnail_jpeg_base64": thumbs, "correction_counts": counts,
            "reference_sha256": hashlib.sha256(canonical.read_bytes()).hexdigest(),
            "source_preserved": True, "production_ready": False,
            "visual_acceptance": "awaiting_visual_comparison",
            "rig_added": False, "animation_rendered": False}


def _mia_hair_identity_pass_three_script() -> str:
    """Deterministic Blender script to rebuild *actual* hair 3D geometry."""
    return r'''import bpy, json, os, sys, math
from mathutils import Vector
data = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
out = data["output"]
scene = bpy.context.scene
counts = {"swept_fringe_groups": 0, "swept_fringe_vertices": 0,
          "crown_locks_hidden": 0, "crown_fibers_hidden": 0,
          "fringe_fibers_hidden": 0, "back_locks_softened": 0,
          "back_locks_hidden": 0, "back_fibers_hidden": 0,
          "bun_loops_hidden": 0, "bun_fibers_hidden": 0,
          "hair_materials_softened": 0}
# One authoritative THREE-DIMENSIONAL mesh. Do not touch face, eyes,
# age proportions, jacket, boots, reference image or any animation.
for ob in bpy.data.objects:
    if ob.type != "MESH" or not ob.data.vertices:
        continue
    n = ob.name.lower()
    if n.startswith("side_swept_fringe_"):
        for v in ob.data.vertices:
            # More continuous asymmetric side part, flatter against forehead.
            t = max(0.0, min(1.0, (3.99-v.co.z) / 0.39))
            v.co.x -= 0.044*t
            v.co.y += 0.014*t
            counts["swept_fringe_vertices"] += 1
        ob.data.update()
        counts["swept_fringe_groups"] += 1
    elif n.startswith("crown_flow_lock_"):
        counts["crown_locks_hidden"] += 1
        if counts["crown_locks_hidden"] % 3 == 0:
            ob.hide_render = True
    elif n.startswith("natural_crown_fiber_"):
        counts["crown_fibers_hidden"] += 1
        if counts["crown_fibers_hidden"] % 4 != 0:
            ob.hide_render = True
    elif n.startswith("fringe_fine_fiber_"):
        counts["fringe_fibers_hidden"] += 1
        if counts["fringe_fibers_hidden"] % 4 != 0:
            ob.hide_render = True
    elif n.startswith("gathered_back_lock_"):
        counts["back_locks_softened"] += 1
        if counts["back_locks_softened"] % 2:
            # Keep the sculpt and its original vertices reversible in .blend,
            # but remove overly regular parallel back locks from the render.
            ob.hide_render = True
            counts["back_locks_hidden"] += 1
        else:
            for v in ob.data.vertices:
                v.co.x *= .96
                v.co.z -= .012
            ob.data.update()
    elif n.startswith("gathered_fine_back_fiber"):
        counts["back_fibers_hidden"] += 1
        if counts["back_fibers_hidden"] % 5 != 0:
            ob.hide_render = True
    elif n.startswith("loose_bun_loop_"):
        counts["bun_loops_hidden"] += 1
        if counts["bun_loops_hidden"] % 2 == 0:
            ob.hide_render = True
    elif n.startswith("bun_fine_fiber"):
        counts["bun_fibers_hidden"] += 1
        if counts["bun_fibers_hidden"] % 4 != 0:
            ob.hide_render = True
# Reduce the artificial hard, corded surface caused by bump relief.
for mat in bpy.data.materials:
    if not mat.use_nodes or not mat.name.lower().startswith("hair_"):
        continue
    did = False
    for node in mat.node_tree.nodes:
        if node.type == "BUMP":
            node.inputs["Strength"].default_value = min(
                node.inputs["Strength"].default_value, .065)
            did = True
    if did:
        counts["hair_materials_softened"] += 1
if (counts["swept_fringe_groups"] < 3 or counts["back_locks_softened"] < 8
        or counts["crown_fibers_hidden"] < 30 or counts["bun_fibers_hidden"] < 20):
    raise RuntimeError("Original Mia hair mesh groups missing: refuse no-op")
scene["identity_status"] = "UNAPPROVED_MIA_HAIR_PASS_3"
scene["parent_model"] = data["parent_blend"]
scene["mesh_corrections"] = json.dumps(counts, sort_keys=True)
blend = os.path.join(out, "mia_reference_model.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend)
camera = scene.camera
if camera is None:
    raise RuntimeError("Fixed review camera missing")
camera.data.type = "ORTHO"
camera.data.ortho_scale = 4.10
scene.render.resolution_percentage = 100
scene.render.resolution_x = 600
scene.render.resolution_y = 900
scene.render.image_settings.file_format = "PNG"

def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
views = (("front", (0,-8,2.30)), ("three_quarter", (5.5,-7,2.45)),
         ("side", (8,0,2.30)), ("back", (0,8,2.30)))
for name, location in views:
    camera.location = location
    aim(camera, (0,0,1.87))
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = os.path.join(out, name + ".png")
    bpy.ops.render.render(write_still=True)
    if name in ("front", "side", "back"):
        pic = bpy.data.images.load(scene.render.filepath, check_existing=False)
        pic.scale(160, 240)
        previous = (scene.view_settings.view_transform, scene.view_settings.look,
                    scene.view_settings.exposure, scene.view_settings.gamma)
        try:
            scene.view_settings.view_transform = "Standard"
            scene.view_settings.look = "None"
            scene.view_settings.exposure = 0
            scene.view_settings.gamma = 1
            scene.render.image_settings.file_format = "JPEG"
            scene.render.image_settings.quality = 60
            pic.save_render(os.path.join(out, name + "_thumb.jpg"), scene=scene)
        finally:
            scene.view_settings.view_transform = previous[0]
            scene.view_settings.look = previous[1]
            scene.view_settings.exposure = previous[2]
            scene.view_settings.gamma = previous[3]
            bpy.data.images.remove(pic)
camera.data.ortho_scale = 1.45
camera.location = (.70,-7,3.20)
aim(camera, (0,-.04,3.12))
scene.render.resolution_x = 256
scene.render.resolution_y = 256
scene.render.image_settings.file_format = "JPEG"
scene.render.image_settings.quality = 55
scene.render.filepath = os.path.join(out, "face_thumb.jpg")
bpy.ops.render.render(write_still=True)
with open(os.path.join(out, "model_result.json"), "w", encoding="utf-8") as f:
    json.dump({"correction_counts": counts, "source_model": data["parent_blend"],
               "video_rendered": False, "visual_approval": False,
               "geometry_modified": True},
              f, ensure_ascii=False, indent=2)
'''



def _mia_reference_model_script() -> str:
    """Bundled custom-mesh Mia look-development script; visual approval pending."""
    return '"""Build a genuine, static three-dimensional Mia look-development asset.\n\nRun with Blender 5.2 --background --python this_file -- config.json.\nThis procedural sculpt is an unapproved interpretation, not a reconstructed rig.\nAll visible character parts have volumetric mesh geometry. No reference billboard.\n"""\nimport bpy\nimport json\nimport math\nimport os\nimport random\nimport sys\nfrom mathutils import Vector\n\nrandom.seed(268)\nPI = math.pi\nTAU = 2 * PI\nCHARACTER = []\n\n\ndef material(name, color, roughness=0.5, metallic=0.0, fabric=False):\n    mat = bpy.data.materials.new(name)\n    mat.diffuse_color = (*color, 1)\n    mat.use_nodes = True\n    tree = mat.node_tree\n    bsdf = tree.nodes.get(\'Principled BSDF\')\n    bsdf.inputs[\'Base Color\'].default_value = (*color, 1)\n    bsdf.inputs[\'Roughness\'].default_value = roughness\n    bsdf.inputs[\'Metallic\'].default_value = metallic\n    if name.startswith(\'Skin\'):\n        bsdf.inputs[\'Subsurface Weight\'].default_value = 0.075\n        bsdf.inputs[\'Subsurface Radius\'].default_value = (1.0, 0.45, 0.25)\n    if fabric:\n        noise = tree.nodes.new(\'ShaderNodeTexNoise\')\n        noise.inputs[\'Scale\'].default_value = 185\n        noise.inputs[\'Detail\'].default_value = 2\n        bump = tree.nodes.new(\'ShaderNodeBump\')\n        bump.inputs[\'Strength\'].default_value = 0.13\n        bump.inputs[\'Distance\'].default_value = 0.009\n        tree.links.new(noise.outputs[\'Fac\'], bump.inputs[\'Height\'])\n        tree.links.new(bump.outputs[\'Normal\'], bsdf.inputs[\'Normal\'])\n        bsdf.inputs[\'Sheen Weight\'].default_value = 0.22\n    if name.startswith(\'Hair_\'):\n        bsdf.inputs[\'Roughness\'].default_value=0.59\n        bsdf.inputs[\'Specular IOR Level\'].default_value=0.22\n        bsdf.inputs[\'Sheen Weight\'].default_value=0.12\n        noise=tree.nodes.new(\'ShaderNodeTexNoise\')\n        noise.inputs[\'Scale\'].default_value=230\n        noise.inputs[\'Detail\'].default_value=3\n        bump=tree.nodes.new(\'ShaderNodeBump\')\n        bump.inputs[\'Strength\'].default_value=0.18\n        bump.inputs[\'Distance\'].default_value=0.008\n        tree.links.new(noise.outputs[\'Fac\'],bump.inputs[\'Height\'])\n        tree.links.new(bump.outputs[\'Normal\'],bsdf.inputs[\'Normal\'])\n    return mat\n\n\ndef mesh(name, vertices, faces, mat, smooth=True, subd=0, character=True):\n    data = bpy.data.meshes.new(name + \'_mesh\')\n    data.from_pydata(vertices, [], faces)\n    data.update()\n    obj = bpy.data.objects.new(name, data)\n    bpy.context.collection.objects.link(obj)\n    obj.data.materials.append(mat)\n    if smooth:\n        for poly in data.polygons:\n            poly.use_smooth = True\n    if subd:\n        mod = obj.modifiers.new(\'Smooth designed surface\', \'SUBSURF\')\n        mod.levels = subd\n        mod.render_levels = subd\n    if character:\n        CHARACTER.append(obj)\n    return obj\n\n\ndef ellipsoid(name, center, scale, mat, n=48, rings=28):\n    """Closed parametric mesh, used for small organic details and eyes."""\n    vertices = []\n    for j in range(rings + 1):\n        th = PI * j / rings\n        for i in range(n):\n            ph = TAU * i / n\n            vertices.append((center[0] + scale[0] * math.sin(th) * math.cos(ph),\n                             center[1] + scale[1] * math.sin(th) * math.sin(ph),\n                             center[2] + scale[2] * math.cos(th)))\n    faces = []\n    for j in range(rings):\n        for i in range(n):\n            a = j*n+i\n            b = j*n+(i+1)%n\n            faces.append((a+n,b+n,b,a))\n    return mesh(name, vertices, faces, mat)\n\n\ndef catmull(points, samples=8):\n    pts = [Vector(p) for p in points]\n    expanded = [pts[0]] + pts + [pts[-1]]\n    out = []\n    for k in range(len(pts)-1):\n        p0,p1,p2,p3 = expanded[k:k+4]\n        for i in range(samples):\n            t=i/samples\n            out.append(0.5*((2*p1)+(-p0+p2)*t+(2*p0-5*p1+4*p2-p3)*t*t+(-p0+3*p1-3*p2+p3)*t*t*t))\n    out.append(pts[-1])\n    return out\n\n\ndef tube(name, points, radii, mat, sides=12, samples=6, flatten=1.0):\n    """Swept closed mesh with smoothly changing cross sections and taper."""\n    path=catmull(points, samples)\n    verts=[]\n    for j,p in enumerate(path):\n        t=j/(len(path)-1)\n        ri=t*(len(radii)-1)\n        r=radii[min(int(ri),len(radii)-1)]\n        if int(ri)<len(radii)-1:\n            r=r*(1-(ri-int(ri)))+radii[int(ri)+1]*(ri-int(ri))\n        tangent=(path[min(j+1,len(path)-1)]-path[max(0,j-1)]).normalized()\n        seed=Vector((0,1,0)) if abs(tangent.y)<0.9 else Vector((1,0,0))\n        a=tangent.cross(seed).normalized()\n        b=tangent.cross(a).normalized()\n        for i in range(sides):\n            ang=TAU*i/sides\n            q=p+a*(r*math.cos(ang))+b*(r*flatten*math.sin(ang))\n            verts.append(tuple(q))\n    faces=[]\n    for j in range(len(path)-1):\n        for i in range(sides):\n            a=j*sides+i;b=j*sides+(i+1)%sides\n            faces.append((a,b,b+sides,a+sides))\n    faces.extend([tuple(range(sides-1,-1,-1)),tuple((len(path)-1)*sides+i for i in range(sides))])\n    return mesh(name,verts,faces,mat)\n\n\ndef loft(name, rings, mat, count=48, folds=0.0, subd=2):\n    """Sewn silhouette loft: rings are (z, width, depth, xcenter, ycenter)."""\n    verts=[]\n    for j,(z,w,d,x,y) in enumerate(rings):\n        for i in range(count):\n            a=TAU*i/count\n            crease=folds*math.sin(6*a+j*1.7)*math.sin(PI*j/(len(rings)-1))\n            verts.append((x+(w+crease)*math.cos(a),y+(d+crease*0.6)*math.sin(a),z))\n    faces=[]\n    for j in range(len(rings)-1):\n        for i in range(count):\n            a=j*count+i;b=j*count+(i+1)%count\n            faces.append((a,b,b+count,a+count))\n    faces.extend([tuple(range(count-1,-1,-1)),tuple((len(rings)-1)*count+i for i in range(count))])\n    return mesh(name,verts,faces,mat,subd=subd)\n\n\ndef rounded_box(name, center, half, mat, bevel=0.06):\n    x,y,z=center;a,b,c=half\n    vertices=[(x+sx*a,y+sy*b,z+sz*c) for sx,sy,sz in\n              [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)]]\n    faces=[(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]\n    obj=mesh(name,vertices,faces,mat)\n    mod=obj.modifiers.new(\'Sewn rounded edge\',\'BEVEL\');mod.width=bevel;mod.segments=5\n    return obj\n\n\ndef build_head(skin, lips, white, iris, pupil, hair, gold, pink):\n    n=112; rows=80; verts=[]; colors=[]\n    for j in range(rows+1):\n        t=PI*j/rows\n        for i in range(n):\n            a=TAU*i/n\n            zz=3.50+0.50*math.cos(t)\n            # Fuller forehead and round cheeks; small pointed-but-soft chin.\n            w=0.505*(0.98+0.055*math.exp(-((zz-3.31)/0.18)**2))\n            x=w*(math.sin(t)**0.88)*math.cos(a)\n            y=0.415*(math.sin(t)**0.95)*math.sin(a)\n            if y<0:\n                front=(-math.sin(a))**8\n                nose=0.073*math.exp(-(x/0.073)**2-((zz-3.29)/0.085)**2)\n                cheeks=0.045*(math.exp(-((x-0.265)/0.16)**2-((zz-3.24)/0.15)**2)+math.exp(-((x+0.265)/0.16)**2-((zz-3.24)/0.15)**2))\n                socket=0.038*(math.exp(-((x-0.225)/0.17)**2-((zz-3.43)/0.16)**2)+math.exp(-((x+0.225)/0.17)**2-((zz-3.43)/0.16)**2))\n                muzzle=0.036*math.exp(-(x/0.19)**2-((zz-3.17)/0.095)**2)\n                y-=front*(nose+cheeks+muzzle-socket)\n            verts.append((x,y,zz))\n            blush=(math.exp(-((abs(x)-0.28)/0.125)**2-((zz-3.23)/0.105)**2)*max(0,-math.sin(a))**10)*0.86\n            base=(0.85,0.365,0.215); rosy=(0.86,0.17,0.105)\n            colors.append(tuple(base[k]*(1-blush)+rosy[k]*blush for k in range(3))+(1,))\n    faces=[]\n    for j in range(rows):\n        for i in range(n):\n            q=j*n+i;r=j*n+(i+1)%n\n            faces.append((q+n,r+n,r,q))\n    head=mesh(\'Mia_Sculpted_Head\',verts,faces,skin)\n    attr=head.data.color_attributes.new(name=\'SkinTone\',type=\'FLOAT_COLOR\',domain=\'POINT\')\n    for idx,c in enumerate(colors):attr.data[idx].color=c\n    skin_head=skin.copy();skin_head.name=\'Skin_Head_With_Painted_Cheeks\';head.data.materials[0]=skin_head\n    node=skin_head.node_tree.nodes.new(\'ShaderNodeVertexColor\');node.layer_name=\'SkinTone\'\n    skin_head.node_tree.links.new(node.outputs[\'Color\'],skin_head.node_tree.nodes.get(\'Principled BSDF\').inputs[\'Base Color\'])\n    for s in (-1,1):\n        ellipsoid(\'Ear_\'+str(s),(s*0.495,-0.005,3.34),(0.095,0.075,0.14),skin)\n        ellipsoid(\'Ear_inner_\'+str(s),(s*0.533,-0.055,3.34),(0.046,0.018,0.085),pink,32,20)\n        # Smaller buried eyeballs; broad brown irises leave little visible white.\n        cx=s*0.217\n        ez=3.43\n        ellipsoid(\'Eye_sclera_\'+str(s),(cx,-0.316,ez),(0.137,0.092,0.155),white,64,40)\n        ellipsoid(\'Eye_iris_\'+str(s),(cx,-0.400,ez-0.003),(0.105,0.016,0.116),iris,64,40)\n        ellipsoid(\'Eye_pupil_\'+str(s),(cx,-0.416,ez+0.001),(0.064,0.007,0.077),pupil,48,28)\n        iris_detail=material(\'Iris_matte_radial_brown_\'+str(s),(.125,.046,.016),.48)\n        for k in range(32):\n            ang=TAU*k/32+random.uniform(-.018,.018)\n            p=(cx+0.072*math.cos(ang),-0.420,ez-0.003+0.085*math.sin(ang))\n            q=(cx+0.091*math.cos(ang),-0.413,ez-0.003+0.104*math.sin(ang))\n            tube(\'Iris_fleck\', [p,q], [0.0008,0.00035],iris_detail,sides=5,samples=1)\n        ellipsoid(\'Eye_catchlight_\'+str(s),(cx-0.031,-0.425,ez+0.046),(0.019,0.006,0.024),white,24,16)\n        ellipsoid(\'Eye_catchlight_small_\'+str(s),(cx+0.035,-0.423,ez-0.031),(0.008,0.003,0.009),white,20,12)\n        # Skin lid bands bridge the eye boundary to the surrounding face.\n        for upper in (True,False):\n            pts=[];strip=[]\n            for k in range(21):\n                a=PI*k/20\n                x=cx-0.136*math.cos(a)\n                sign=1 if upper else -1\n                z=ez+sign*(0.129 if upper else 0.122)*math.sin(a)\n                y=-0.357-0.044*math.sin(a)\n                pts.append((x,y,z))\n                strip.extend([(x,y,z),(x,-0.328-0.022*math.sin(a),z+sign*0.049*math.sin(a))])\n            faces=[(2*k,2*k+1,2*k+3,2*k+2) for k in range(20)]\n            if not upper:faces=[tuple(reversed(f)) for f in faces]\n            mesh(\'Lid_skin_transition\',strip,faces,skin,subd=1)\n            tube(\'Upper_eyelid\' if upper else \'Lower_eyelid\',pts,([0.005,0.010,0.004] if upper else [0.003,0.005,0.003]),skin,sides=10,samples=2)\n        outline=[]\n        for k in range(15):\n            a=PI*k/14\n            outline.append((cx-0.135*math.cos(a),-0.362-0.043*math.sin(a),ez+0.131*math.sin(a)))\n        tube(\'Fine_upper_lash_line\',outline,[0.003,0.006,0.003],hair[0],sides=8,samples=2)\n        for k in range(3):\n            x=cx+s*(0.105+0.010*k); z=ez+0.071-0.021*k\n            tube(\'Outer_lash\',[(x,-0.380,z),(x+s*0.019,-0.413,z+0.018),(x+s*0.023,-0.416,z+0.025)], [0.0035,0.003,0.0004],hair[0],sides=6,samples=4)\n        tube(\'Soft_child_brow\',[(cx-s*0.116,-0.365,3.635),(cx,-0.382,3.66),(cx+s*0.11,-0.333,3.636)], [0.006,0.014,0.003],hair[1],sides=10,samples=7,flatten=0.4)\n        # Nose wings are tiny, no cartoon disk or oversized mouth object.\n        ellipsoid(\'Nose_ala_\'+str(s),(s*0.034,-0.451,3.285),(0.029,0.020,0.023),skin,32,20)\n    mouth=[(-0.118,-0.352,3.187),(-0.065,-0.369,3.158),(0,-0.376,3.155),(0.065,-0.369,3.158),(0.118,-0.352,3.187)]\n    tube(\'Gentle_closed_smile\',mouth,[0.003,0.006,0.006,0.006,0.002],lips,sides=10,samples=7,flatten=0.5)\n    tube(\'Lower_lip\', [(-0.07,-0.372,3.148),(0,-0.380,3.140),(0.07,-0.372,3.148)],[0.003,0.007,0.003],pink,sides=10,samples=8,flatten=0.5)\n    # Scalp fitted to head with an asymmetric hairline.\n    v=[];f=[]; cols=96; rings=32\n    for j in range(rings+1):\n        for i in range(cols):\n            a=TAU*i/cols\n            front=max(0,-math.sin(a))\n            end=1.93-0.90*front+0.10*math.cos(a)*front\n            th=0.004+(end-0.004)*j/rings\n            v.append((0.53*math.sin(th)*math.cos(a),0.431*math.sin(th)*math.sin(a),3.44+0.577*math.cos(th)))\n    for j in range(rings):\n        for i in range(cols):\n            a=j*cols+i;b=j*cols+(i+1)%cols\n            f.append((a+cols,b+cols,b,a))\n    mesh(\'Swept_hair_cap\',v,f,hair[1])\n    # Broad sculpted locks radiate from a side part and sweep over the crown.\n    for k in range(23):\n        a=TAU*k/23+0.06*math.sin(k*2.1)\n        front=max(0,-math.sin(a)); end=1.87-0.78*front+0.13*math.cos(a)*front\n        pts=[]\n        for j in range(7):\n            t=j/6; th=0.12+(end-0.12)*t\n            ang=a+0.43*(1-t)+0.07*math.sin(PI*t)\n            x=0.548*math.sin(th)*math.cos(ang)\n            y=0.447*math.sin(th)*math.sin(ang)\n            z=3.455+0.59*math.cos(th)\n            pts.append((x,y,z))\n        width=0.030+0.020*random.random()\n        tube(\'Crown_flow_lock_%02d\'%k,pts,[0.003,width,width*0.9,0.003],hair[1+(k%3)],sides=12,samples=5,flatten=0.16)\n        # Fine highlights follow lock curvature, offset very slightly outward.\n        hpts=[(x*1.016,y*1.016,z+0.006) for x,y,z in pts]\n        tube(\'Crown_strand_%02d\'%k,hpts,[0.001,0.0025,0.002,0.0004],hair[4],sides=5,samples=5)\n    # Three overlapping, diagonal front locks make the reference\'s side-swept fringe.\n    for k in range(4):\n        d=k*0.046\n        pts=[(0.30-d,-0.22,3.973),(0.20-d,-0.40,3.964),(-0.01-d,-0.452,3.885),(-0.18-d,-0.448,3.769),(-0.34-d*0.5,-0.342,3.64)]\n        tube(\'Side_swept_fringe_%02d\'%k,pts,[0.008,0.060,0.051,0.001],hair[1+k%3],sides=12,samples=6,flatten=0.16)\n    # Back locks gather toward a low bun, keeping the side silhouette curved.\n    for k in range(19):\n        a=PI*k/18+0.035*math.sin(k*1.9)\n        x=0.51*math.cos(a);z=3.47+0.46*math.sin(a)\n        pts=[(x,0.27,z),(x*0.88,0.43,z-0.09),(x*0.52,0.49,3.47),(0.05,0.49,3.28)]\n        tube(\'Gathered_back_lock_%02d\'%k,pts,[0.010,0.040,0.028,0.005],hair[1+k%3],sides=10,samples=6,flatten=0.20)\n    ellipsoid(\'Low_bun_core\',(0.045,0.48,3.26),(0.20,0.15,0.19),hair[1])\n    for k in range(13):\n        ph=TAU*k/13+random.uniform(-.12,.12)\n        pts=[]\n        for j in range(10):\n            t=j/9; a=ph+TAU*0.78*t\n            pts.append((0.045+0.21*math.sin(a)*(0.8+0.2*math.sin(PI*t)),0.48+0.14*math.cos(a),3.25+0.19*math.sin(PI*(t-.5))))\n        tube(\'Loose_bun_loop_%02d\'%k,pts,[0.003,0.018,0.023,0.001],hair[1+k%3],sides=10,samples=3,flatten=0.7)\n    for s in (-1,1):\n        for k in range(3):\n            pts=[(s*(0.46+0.013*k),-0.08,3.62),(s*(0.505+0.014*k),-0.095,3.44),(s*(0.525+0.018*k),-0.033,3.28),(s*(0.485+0.023*k),0.025,3.225),(s*(0.50+0.024*k),0.065,3.29)]\n            tube(\'Wispy_face_curl\',pts,[0.007,0.010,0.006,0.0006],hair[2+k%2],sides=9,samples=6)\n    # Dense, individually curved fibers break the broad sculpted locks into hair.\n    # Every strand is a tapered volumetric mesh, with no image-texture shortcut.\n    for k in range(190):\n        a=TAU*k/190+random.uniform(-.024,.024)\n        front=max(0,-math.sin(a))\n        end=1.88-0.80*front+0.12*math.cos(a)*front\n        phase=random.uniform(0,TAU)\n        pts=[]\n        for j in range(10):\n            t=j/9; th=.14+(end-.14)*t\n            ang=a+.43*(1-t)+.045*math.sin(3*PI*t+phase)*t\n            rr=1+.014*math.sin(2*PI*t+phase)\n            pts.append((.550*rr*math.sin(th)*math.cos(ang),.449*rr*math.sin(th)*math.sin(ang),3.459+.591*math.cos(th)))\n        tube(\'Natural_crown_fiber_%03d\'%k,pts,[.0008,.0018,.0015,.00015],hair[2+k%3],sides=5,samples=3)\n    for k in range(110):\n        t=k/109; off=.175*t\n        phase=random.uniform(0,TAU)\n        pts=[(.30-off,-.227,3.977),(.21-off,-.406,3.970),(.012-off,-.459,3.900),(-.165-off,-.453,3.785),(-.338-off*.5,-.35,3.657)]\n        pts=[(x+.006*math.sin(phase+j*1.2),y-.003*math.sin(phase+j),z+.003*math.sin(phase+j*1.5)) for j,(x,y,z) in enumerate(pts)]\n        tube(\'Fringe_fine_fiber_%03d\'%k,pts,[.0008,.0015,.0011,.0001],hair[2+k%3],sides=5,samples=5)\n    for k in range(100):\n        a=PI*k/99+random.uniform(-.01,.01)\n        x=.513*math.cos(a);z=3.477+.463*math.sin(a)\n        pts=[(x,.277,z),(x*.88,.436,z-.09),(x*.52,.499,3.473),(.05,.50,3.28)]\n        tube(\'Gathered_fine_back_fiber\',pts,[.0008,.0016,.0012,.0002],hair[2+k%3],sides=5,samples=5)\n    for k in range(65):\n        ph=TAU*k/65+random.uniform(-.025,.025)\n        pts=[]\n        for j in range(10):\n            t=j/9;a=ph+TAU*.78*t\n            pts.append((.045+.212*math.sin(a)*(.8+.2*math.sin(PI*t)),.483+.142*math.cos(a),3.251+.191*math.sin(PI*(t-.5))))\n        tube(\'Bun_fine_fiber\',pts,[.0008,.0017,.0012,.0002],hair[2+k%3],sides=5,samples=3)\n    for s in (-1,1):\n        for k in range(10):\n            shift=k*.0035;phase=random.uniform(0,TAU)\n            pts=[(s*(.46+shift),-.11,3.62),(s*(.50+shift),-.14,3.43),(s*(.535+shift),-.072,3.25),(s*(.47+shift),.013,3.20),(s*(.495+shift),.066,3.275)]\n            tube(\'Soft_temporal_wisp\',pts,[.0025,.004,.002,.0002],hair[2+k%2],sides=6,samples=5)\n        for k in range(5):\n            x=s*(.12+k*.029)\n            pts=[(x,.56,3.26),(x+s*.026,.61,3.14),(x+s*.006,.58,3.09),(x-s*.025,.55,3.15)]\n            tube(\'Loose_bun_end_curl\',pts,[.004,.009,.006,.0002],hair[2+k%2],sides=7,samples=6)\n    # Flyaway strands are actual curved round geometry.\n    for k in range(14):\n        a=TAU*k/14\n        pts=[(0.50*math.cos(a),0.38*math.sin(a),3.72),(.57*math.cos(a),.46*math.sin(a),3.88),(.53*math.cos(a),.46*math.sin(a),3.95)]\n        tube(\'Fine_flyaway\',pts,[0.0018,0.0018,0.0003],hair[3],sides=5,samples=5)\n\n\ndef build_clothes(skin, teal, teal_dark, cuff, lining, pants, seam, boot, sole, gold, bag, bag_dark):\n    # Neck and hoodie: custom smoothly lofted surfaces, not segmented cylinders.\n    loft(\'Neck\',[(2.70,.12,.11,0,0),(2.73,.14,.115,0,0),(2.96,.14,.12,0,0),(3.01,.11,.11,0,0)],skin,subd=2)\n    loft(\'Tailored_zip_hoodie\',[(1.73,.35,.205,0,0),(1.76,.365,.215,0,0),(1.81,.365,.215,0,0),(2.00,.36,.22,0,0),(2.23,.35,.22,0,0),(2.47,.37,.23,0,0),(2.65,.36,.21,0,0),(2.76,.245,.15,0,0),(2.78,.22,.14,0,0)],teal,folds=.013)\n    loft(\'Ribbed_hoodie_hem\',[(1.71,.345,.209,0,0),(1.73,.36,.22,0,0),(1.80,.36,.22,0,0),(1.815,.35,.21,0,0)],cuff,subd=1)\n    # Hood hangs behind neck, with folded opening surrounding the shoulders.\n    loft(\'Collapsed_hood\',[(2.53,.20,.105,0,.16),(2.56,.25,.14,0,.20),(2.73,.29,.16,0,.17),(2.92,.24,.145,0,.10),(2.95,.20,.11,0,.08)],teal_dark,subd=2)\n    for s in (-1,1):\n        tube(\'Pale_hood_lining\',[(s*.05,-.16,2.91),(s*.15,-.16,2.82),(s*.225,-.135,2.72),(s*.29,-.005,2.65)],[.025,.045,.037,.018],lining,sides=12,samples=7)\n        tube(\'Hood_fold_edge\',[(s*.08,-.135,2.93),(s*.22,-.08,2.86),(s*.28,.035,2.69),(s*.27,.13,2.59)],[.025,.035,.035,.018],teal,sides=12,samples=7)\n        # Relaxed A-pose sleeves: tailored elbow bulge and narrowing cuffs.\n        path=[(s*.31,0,2.63),(s*.425,0,2.56),(s*.515,-.015,2.37),(s*.60,-.035,2.17),(s*.70,-.06,1.96),(s*.72,-.075,1.91)]\n        tube(\'Soft_hoodie_sleeve_\'+str(s),path,[.17,.17,.14,.14,.11,.105],teal,sides=32,samples=9)\n        tube(\'Ribbed_sleeve_cuff_\'+str(s),[(s*.697,-.06,1.97),(s*.723,-.075,1.91),(s*.733,-.08,1.88)],[.112,.109,.101],cuff,sides=32,samples=5)\n        # Short soft crease ridges on sleeve and knee, integrated visually in cloth.\n        for k in range(3):\n            tube(\'Sleeve_elbow_fold\',[(s*(.50+.018*k),-.128,2.35-.055*k),(s*(.56+.018*k),-.157,2.31-.055*k),(s*(.615+.014*k),-.115,2.27-.055*k)], [.004,.012,.003],teal_dark,sides=8,samples=5)\n        tube(\'Sleeve_seam\',[(s*.36,-.14,2.64),(s*.50,-.145,2.39),(s*.61,-.155,2.15),(s*.71,-.15,1.94)],[.004,.004,.004,.002],cuff,sides=7,samples=7)\n        # Anatomical palm and five curved fingers, all separate closed organic meshes.\n        cx=s*.759\n        ellipsoid(\'Child_palm_\'+str(s),(cx,-.073,1.797),(.090,.046,.129),skin,40,28)\n        for f in range(4):\n            xx=cx+s*(-.056+f*.035)\n            length=[.115,.145,.138,.105][f]\n            pts=[(xx,-.088,1.738),(xx+s*.010,-.106,1.698),(xx+s*.010,-.096,1.738-length),(xx+s*.006,-.086,1.73-length)]\n            tube(\'Finger_%s_%s\'%(s,f),pts,[.022,.024,.020,.008],skin,sides=12,samples=6)\n        tube(\'Thumb_\'+str(s),[(cx-s*.067,-.074,1.83),(cx-s*.107,-.103,1.783),(cx-s*.115,-.125,1.733)],[.027,.027,.015],skin,sides=12,samples=8)\n    # Fabric front pockets, seams, gold zipper teeth.\n    for s in (-1,1):\n        rounded_box(\'Kangaroo_pocket_\'+str(s),(s*.177,-.205,1.967),(.145,.027,.128),teal,bevel=.035)\n        tube(\'Pocket_slanted_welt\',[(s*.09,-.243,2.08),(s*.195,-.239,2.09),(s*.29,-.223,2.12)],[.006,.008,.005],cuff,sides=8,samples=5)\n        tube(\'Pocket_lower_stitch\',[(s*.055,-.244,1.872),(s*.18,-.245,1.866),(s*.30,-.22,1.878)],[.003,.003,.003],seam,sides=6,samples=5)\n        tube(\'Hood_drawstring\',[(s*.12,-.18,2.74),(s*.11,-.236,2.61),(s*.12,-.257,2.46)],[.009,.009,.007],gold,sides=9,samples=8)\n        rounded_box(\'Drawstring_tip\',(s*.12,-.259,2.455),(.009,.008,.022),gold,.005)\n    tube(\'Zipper_dark_tape\',[(0,-.235,1.78),(0,-.245,2.14),(0,-.252,2.48),(0,-.195,2.73)],[.014,.014,.014,.010],teal_dark,sides=10,samples=9)\n    for k in range(54):\n        z=1.80+k*.0165;y=-.239-.012*math.sin((z-1.8)*PI)\n        rounded_box(\'Golden_zip_tooth\',((-1 if k%2 else 1)*.006,y-.010,z),(.008,.005,.004),gold,.002)\n    rounded_box(\'Zipper_pull\',(0,-.232,2.68),(.020,.014,.046),gold,.008)\n    # Trousers pelvis is covered by hoodie; pant legs sculpt through the knees.\n    loft(\'Trousers_hip\',[(1.54,.29,.18,0,0),(1.58,.335,.20,0,0),(1.75,.32,.19,0,0),(1.82,.30,.18,0,0)],pants,folds=.008)\n    for s in (-1,1):\n        x=s*.185\n        loft(\'Cargo_trouser_leg_\'+str(s),[(.42,.125,.115,x,-.006),(.445,.135,.125,x,0),(.50,.15,.132,x,0),(.59,.154,.135,x,.003),(.65,.138,.125,x,.01),(.72,.153,.13,x,.004),(.88,.145,.128,x,.012),(1.05,.169,.138,x,.005),(1.20,.171,.139,x,0),(1.40,.173,.151,x,0),(1.63,.18,.155,x,0),(1.73,.176,.15,x,0)],pants,folds=.022)\n        loft(\'Rolled_trouser_cuff_\'+str(s),[(.42,.129,.12,x,0),(.44,.140,.13,x,0),(.50,.140,.13,x,0),(.515,.129,.12,x,0)],pants,subd=1)\n        # Reference cargo pockets on outer thigh, extending around lateral seam.\n        rounded_box(\'Cargo_side_pocket_\'+str(s),(x+s*.147,-.005,1.27),(.045,.12,.17),pants,.028)\n        rounded_box(\'Cargo_flap_\'+str(s),(x+s*.179,-.01,1.412),(.016,.122,.038),pants,.017)\n        tube(\'Cargo_pocket_stitch\',[(x+s*.193,-.108,1.12),(x+s*.196,.00,1.112),(x+s*.193,.104,1.12)],[.003,.003,.003],seam,sides=6,samples=5)\n        tube(\'Leg_outer_seam\',[(x+s*.131,0,.48),(x+s*.15,0,.84),(x+s*.177,0,1.25),(x+s*.18,0,1.58)],[.003,.003,.003,.002],seam,sides=6,samples=7)\n        for k in range(3):\n            z=.65+.13*k\n            tube(\'Trouser_soft_fold\',[(x-.10,-.091,z),(x,-.14,z-.025),(x+.09,-.107,z+.014)],[.003,.007,.002],pants,sides=8,samples=5)\n        # Tan ankle boots with independent rounded sole, toe box, ankle upper.\n        loft(\'Boot_upper_\'+str(s),[(.085,.155,.235,x,-.067),(.11,.17,.255,x,-.08),(.17,.169,.251,x,-.08),(.23,.157,.208,x,-.046),(.29,.13,.15,x,-.01),(.40,.126,.124,x,.013),(.47,.129,.121,x,.012),(.49,.115,.108,x,.012)],boot,subd=2)\n        loft(\'Boot_rubber_sole_\'+str(s),[(.035,.147,.235,x,-.085),(.044,.165,.26,x,-.085),(.075,.173,.266,x,-.085),(.105,.172,.260,x,-.085),(.12,.158,.245,x,-.085)],sole,subd=1)\n        tube(\'Boot_top_padded_collar\',[(x-.12,0,.451),(x-.07,-.094,.46),(x+.07,-.094,.46),(x+.12,0,.451),(x+.07,.108,.451),(x-.07,.108,.451),(x-.12,0,.451)],[.018,.018,.018,.018],pants,sides=10,samples=5)\n        rounded_box(\'Boot_tongue_\'+str(s),(x,-.117,.365),(.075,.018,.089),boot,.020)\n        for k in range(4):\n            z=.273+k*.040\n            y=-.192+k*.019\n            for ss in (-1,1):\n                ellipsoid(\'Boot_eyelet\',(x+ss*.063,y,z),(.013,.006,.013),gold,20,12)\n            tube(\'Boot_cross_lace\',[(x-.064,y-.010,z),(x,y-.020,z+.025),(x+.064,y-.010,z+.020)],[.006,.006,.006],sole,sides=7,samples=4)\n        tube(\'Boot_toe_stitch\',[(x-.13,-.20,.17),(x-.07,-.298,.17),(x+.07,-.298,.17),(x+.13,-.20,.17)],[.003,.003,.003,.003],seam,sides=6,samples=5)\n        for k in range(8):\n            rounded_box(\'Sole_tread\',(x+.157,-.22+k*.043,.07),(.008,.012,.016),pants,.005)\n    # Mustard canvas backpack, rear is +Y.\n    rounded_box(\'Mustard_backpack_main\',(0,.338,2.24),(.30,.145,.385),bag,.105)\n    rounded_box(\'Backpack_rear_front_pocket\',(0,.486,2.07),(.25,.060,.164),bag,.060)\n    rounded_box(\'Backpack_pocket_flap\',(0,.543,2.175),(.254,.027,.055),bag,.025)\n    tube(\'Backpack_main_piping\',[(-.26,.46,1.92),(-.29,.465,2.24),(-.23,.46,2.54),(0,.465,2.62),(.23,.46,2.54),(.29,.465,2.24),(.26,.46,1.92)],[.008,.008,.008,.008],bag_dark,sides=8,samples=6)\n    tube(\'Backpack_zip\',[(-.225,.48,2.48),(-.12,.49,2.57),(0,.49,2.59),(.12,.49,2.57),(.225,.48,2.48)],[.005,.005,.005,.005],gold,sides=8,samples=5)\n    rounded_box(\'Backpack_zip_pull\',(.24,.49,2.46),(.011,.010,.032),gold,.006)\n    tube(\'Backpack_top_loop\',[(-.09,.35,2.615),(-.08,.35,2.69),(.08,.35,2.69),(.09,.35,2.615)],[.015,.015,.015,.015],bag_dark,sides=10,samples=5)\n    for s in (-1,1):\n        tube(\'Mustard_shoulder_strap_\'+str(s),[(s*.20,.25,2.56),(s*.25,.10,2.72),(s*.275,-.15,2.68),(s*.267,-.261,2.43),(s*.29,-.257,2.20),(s*.33,-.08,2.01),(s*.26,.23,1.94)],[.034,.047,.047,.045,.035,.026,.025],bag,sides=12,samples=8,flatten=.45)\n        rounded_box(\'Strap_buckle_\'+str(s),(s*.29,-.28,2.30),(.043,.013,.038),bag_dark,.008)\n        rounded_box(\'Backpack_side_pouch_\'+str(s),(s*.304,.345,2.105),(.035,.105,.136),bag,.027)\n\n\ndef aim(obj, target):\n    obj.rotation_euler=(Vector(target)-obj.location).to_track_quat(\'-Z\',\'Y\').to_euler()\n\n\ndef run():\n    argv=sys.argv[sys.argv.index(\'--\')+1:] if \'--\' in sys.argv else []\n    if argv:\n        with open(argv[0],encoding=\'utf-8\') as cfg_file:\n            config=json.load(cfg_file)\n    else:\n        config={}\n    out=os.path.abspath(config.get(\'output_dir\') or os.path.join(os.getcwd(),\'mia_model_review\'))\n    os.makedirs(out,exist_ok=True)\n    bpy.ops.object.select_all(action=\'SELECT\');bpy.ops.object.delete(use_global=False)\n    skin=material(\'Skin_Warm_Peach\',(.82,.365,.215),.47)\n    pink=material(\'Skin_Lip_Ear\',(.62,.15,.095),.5)\n    lips=material(\'Smile_Deep_Rose\',(.26,.082,.048),.6)\n    white=material(\'Eye_White_Warm\',(.92,.885,.81),.24)\n    iris=material(\'Eye_Brown_Iris\',(.105,.036,.013),.30)\n    pupil=material(\'Eye_Pupil\',(.009,.004,.002),.19)\n    hair=[material(\'Hair_%d\'%i,c,.43) for i,c in enumerate([(.043,.013,.004),(.16,.047,.014),(.22,.069,.022),(.27,.094,.035),(.32,.127,.046)])]\n    gold=material(\'Golden_Hardware\',(.52,.292,.064),.32,.5)\n    teal=material(\'Teal_Cotton_Hoodie\',(.009,.096,.143),.78,fabric=True)\n    teal_dark=material(\'Teal_Fold_Shadow\',(.007,.065,.101),.8,fabric=True)\n    cuff=material(\'Teal_Ribbed_Knit\',(.012,.082,.128),.82,fabric=True)\n    lining=material(\'Pale_Hood_Lining\',(.51,.63,.64),.82,fabric=True)\n    pants=material(\'Brown_Cargo_Twill\',(.26,.121,.061),.82,fabric=True)\n    seam=material(\'Golden_Tan_Stitch\',(.44,.261,.122),.8)\n    boot=material(\'Tan_Leather_Boots\',(.32,.145,.053),.65,fabric=True)\n    sole=material(\'Cream_Rubber_Sole\',(.63,.485,.31),.8)\n    bag=material(\'Mustard_Canvas_Backpack\',(.64,.35,.044),.8,fabric=True)\n    bag_dark=material(\'Backpack_Seam\',(.35,.17,.029),.82)\n    build_head(skin,lips,white,iris,pupil,hair,gold,pink)\n    build_clothes(skin,teal,teal_dark,cuff,lining,pants,seam,boot,sole,gold,bag,bag_dark)\n    # Match the reference\'s short-legged child proportion (~3.6 head heights).\n    # Clothing gets soft volume; hands and facial geometry keep their scale.\n    for obj in CHARACTER:\n        body_volume=any(tag in obj.name for tag in (\'Tailored_zip_hoodie\',\'Ribbed_hoodie_hem\',\'Trousers_hip\',\'Cargo_trouser_leg\',\'Rolled_trouser_cuff\',\'Cargo_side_pocket\',\'Cargo_flap\',\'Cargo_pocket_stitch\',\'Leg_outer_seam\',\'Trouser_soft_fold\',\'Kangaroo_pocket\',\'Pocket_slanted_welt\',\'Pocket_lower_stitch\',\'Zipper_dark_tape\',\'Golden_zip_tooth\',\'Zipper_pull\'))\n        for vertex in obj.data.vertices:\n            x,y,z=vertex.co\n            if body_volume:\n                vertex.co.x=x*1.12\n                vertex.co.y=y*1.10\n            vertex.co.z=(0.5+(z-0.5)*0.75) if 0.5<z<1.8 else (z-0.325 if z>=1.8 else z)\n    # Consolidate static construction modifiers and ensure all transforms are applied.\n    for obj in CHARACTER:\n        bpy.context.view_layer.objects.active=obj\n        obj.select_set(True)\n        for mod in list(obj.modifiers):\n            bpy.ops.object.modifier_apply(modifier=mod.name)\n        bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)\n        obj.select_set(False)\n        obj[\'asset_role\']=\'Mia_reference_model_review_unapproved\'\n    floor=material(\'Neutral_Warm_Studio\',(.30,.30,.29),.9)\n    mesh(\'Studio_Floor\',[(-200,-200,0),(200,-200,0),(200,200,0),(-200,200,0)],[(0,1,2,3)],floor,smooth=False,character=False)\n    scene=bpy.context.scene\n    scene.render.engine=\'CYCLES\'\n    scene.cycles.samples=int(config.get(\'samples\',32))\n    scene.cycles.use_denoising=True\n    scene.cycles.device=\'CPU\'\n    # Prefer the local RTX GPU when available; leave portable CPU fallback.\n    try:\n        prefs=bpy.context.preferences.addons[\'cycles\'].preferences\n        prefs.compute_device_type=\'OPTIX\'\n        prefs.get_devices()\n        devices=[d for d in prefs.devices if d.type==\'OPTIX\']\n        if devices:\n            for device in prefs.devices:device.use=(device.type==\'OPTIX\')\n            scene.cycles.device=\'GPU\'\n    except (TypeError,RuntimeError,KeyError):\n        pass\n    scene.render.resolution_x=600;scene.render.resolution_y=900;scene.render.resolution_percentage=100\n    scene.render.image_settings.file_format=\'PNG\'\n    scene.render.film_transparent=False\n    scene.world.color=(.18,.18,.18)\n    scene.world.use_nodes=True\n    scene.world.node_tree.nodes.get(\'Background\').inputs[\'Color\'].default_value=(.39,.40,.42,1)\n    scene.world.node_tree.nodes.get(\'Background\').inputs[\'Strength\'].default_value=.35\n    world_tree=scene.world.node_tree\n    original_background=world_tree.nodes.get(\'Background\')\n    camera_background=world_tree.nodes.new(\'ShaderNodeBackground\')\n    camera_background.inputs[\'Color\'].default_value=(.42,.415,.405,1)\n    camera_background.inputs[\'Strength\'].default_value=1.0\n    ray=world_tree.nodes.new(\'ShaderNodeLightPath\')\n    mix=world_tree.nodes.new(\'ShaderNodeMixShader\')\n    world_tree.links.new(ray.outputs[\'Is Camera Ray\'],mix.inputs[0])\n    world_tree.links.new(original_background.outputs[0],mix.inputs[1])\n    world_tree.links.new(camera_background.outputs[0],mix.inputs[2])\n    world_tree.links.new(mix.outputs[0],world_tree.nodes.get(\'World Output\').inputs[\'Surface\'])\n    scene.view_settings.view_transform=\'AgX\'\n    scene.view_settings.look=\'AgX - Medium High Contrast\'\n    for name,pos,power,size in [(\'Key\',(-3,-4,6),650,4),(\'Fill\',(3,-2,4),400,3),(\'Rim\',(2,3,5),700,3)]:\n        data=bpy.data.lights.new(name,\'AREA\');data.energy=power;data.shape=\'DISK\';data.size=size\n        obj=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(obj);obj.location=pos;aim(obj,(0,0,2.3))\n    data=bpy.data.cameras.new(\'Mia_Review_Camera\');cam=bpy.data.objects.new(\'Mia_Review_Camera\',data);bpy.context.collection.objects.link(cam)\n    scene.camera=cam;data.type=\'ORTHO\';data.ortho_scale=4.10;data.lens=70\n    bounds=[obj.matrix_world@Vector(c) for obj in CHARACTER for c in obj.bound_box]\n    bmin=[min(p[k] for p in bounds) for k in range(3)];bmax=[max(p[k] for p in bounds) for k in range(3)]\n    scene[\'review_status\']=\'UNAPPROVED_STATIC_MODEL_NOT_ANIMATION_READY\'\n    scene[\'construction\']=\'custom volumetric mesh surfaces; no image plane; no external model\'\n    views=[(\'front\',(0,-8,2.30)),(\'three_quarter\',(5.5,-7,2.45)),(\'side\',(8,0,2.30)),(\'back\',(0,8,2.30))]\n    # Checkpoint the actual model before any render/thumbnail operations.\n    reference_path=config.get(\'reference_path\')\n    if reference_path and os.path.isfile(reference_path):\n        reference=bpy.data.images.load(reference_path,check_existing=True)\n        reference.name=\'Mia_Approved_Reference_Texture_Source\';reference.pack()\n        paint_info=apply_reference_projection(CHARACTER,reference,strength=.50)\n    blend=os.path.join(out,\'mia_reference_model.blend\')\n    cam.location=views[1][1];aim(cam,(0,0,1.87))\n    bpy.ops.wm.save_as_mainfile(filepath=blend)\n    renders={};thumbs={}\n    for name,position in views:\n        cam.location=position;aim(cam,(0,0,1.87))\n        scene.render.resolution_x=600;scene.render.resolution_y=900\n        scene.render.image_settings.file_format=\'PNG\';scene.render.filepath=os.path.join(out,name+\'.png\')\n        bpy.ops.render.render(write_still=True);renders[name]=scene.render.filepath\n        # In background Blender Render Result can have no readable pixels.\n        # Load the written, tonemapped PNG instead, then resize actual pixels.\n        thumb=bpy.data.images.load(scene.render.filepath,check_existing=False)\n        thumb.name=\'ReviewThumbnail_\'+name\n        thumb.scale(160,240)\n        scene.render.image_settings.file_format=\'JPEG\';scene.render.image_settings.quality=60\n        p=os.path.join(out,name+\'_thumb.jpg\')\n        previous=(scene.view_settings.view_transform,scene.view_settings.look,\n                  scene.view_settings.exposure,scene.view_settings.gamma)\n        try:\n            # PNG is already AgX-tonemapped; Standard preserves its appearance.\n            scene.view_settings.view_transform=\'Standard\'\n            scene.view_settings.look=\'None\'\n            scene.view_settings.exposure=0\n            scene.view_settings.gamma=1\n            thumb.save_render(p,scene=scene)\n        finally:\n            scene.view_settings.view_transform=previous[0]\n            scene.view_settings.look=previous[1]\n            scene.view_settings.exposure=previous[2]\n            scene.view_settings.gamma=previous[3]\n            bpy.data.images.remove(thumb)\n        thumbs[name]=p\n    # Additional facial close-up exposes identity quality before animation.\n    cam.data.ortho_scale=1.45;cam.location=(.70,-7,3.20);aim(cam,(0,-.04,3.12))\n    scene.render.resolution_x=256;scene.render.resolution_y=256\n    scene.render.image_settings.file_format=\'JPEG\';scene.render.image_settings.quality=55\n    scene.render.filepath=os.path.join(out,\'face_thumb.jpg\')\n    bpy.ops.render.render(write_still=True)\n    face_thumb=scene.render.filepath\n    cam.data.ortho_scale=4.10\n    scene.render.resolution_x=600;scene.render.resolution_y=900\n    cam.location=views[1][1];aim(cam,(0,0,1.87))\n    scene.render.image_settings.file_format=\'PNG\'\n    blend=os.path.join(out,\'mia_reference_model.blend\');bpy.ops.wm.save_as_mainfile(filepath=blend)\n    summary={\'status\':\'completed\',\'stage\':\'mia_reference_model_review\',\'production_ready\':False,\'visual_acceptance\':\'pending\',\'rigged\':False,\'reference_match_verified\':False,\'reference_paint\':paint_info,\n             \'mesh_count\':len(CHARACTER),\'vertex_count\':sum(len(o.data.vertices) for o in CHARACTER),\n             \'polygon_count\':sum(len(o.data.polygons) for o in CHARACTER),\'bounds\':{\'min\':bmin,\'max\':bmax},\n             \'blend_path\':blend,\'face_thumbnail_path\':face_thumb,\'preview_paths\':renders,\'thumbnail_paths\':{k:v for k,v in thumbs.items() if k in (\'front\',\'side\',\'back\')},\n             \'limitations\':[\'Procedural interpretation, not automatic reconstruction\',\'No body rig or facial blend shapes\',\'Three-view reference paint contains baked illumination; no billboard used\']}\n    with open(os.path.join(out,\'model_result.json\'),\'w\',encoding=\'utf-8\') as f:json.dump(summary,f,ensure_ascii=False,indent=2)\n    print(\'MIA_MODEL_REVIEW_RESULT \'+json.dumps(summary,ensure_ascii=False))\n\n\n"""Optional reference paint on volumetric Mia review meshes.\n\nThis performs camera projection of the approved three-view reference into UV maps.\nIt is appearance paint, not 3D reconstruction or rigging. Existing geometry and\nphysical lighting remain active. Reference shadows are baked and imperfect.\nIntended to be called after static modifiers/transforms have been applied.\n"""\nimport bpy\nimport math\n\n\ndef _math(tree, operation, a, b=None):\n    node=tree.nodes.new(\'ShaderNodeMath\');node.operation=operation\n    if hasattr(a,\'node\'):tree.links.new(a,node.inputs[0])\n    else:node.inputs[0].default_value=a\n    if b is not None:\n        if hasattr(b,\'node\'):tree.links.new(b,node.inputs[1])\n        else:node.inputs[1].default_value=b\n    return node.outputs[0]\n\n\ndef _vec(tree, operation, a, b):\n    node=tree.nodes.new(\'ShaderNodeVectorMath\');node.operation=operation\n    for idx,value in enumerate((a,b)):\n        if hasattr(value,\'node\'):tree.links.new(value,node.inputs[idx])\n        else:node.inputs[idx].default_value=value\n    return node.outputs[\'Vector\']\n\n\ndef _category(obj):\n    name=obj.name.lower()\n    # Refuse image-based duplicate pupils, eyelids, eyelashes, smile, hardware.\n    if any(s in name for s in (\'eye_\',\'iris_\',\'lash\',\'eyelid\',\'lid_skin\',\'smile\',\'lip\',\'nose_ala\',\'zip\',\'buckle\',\'eyelet\',\'drawstring_tip\',\'sole_tread\')):\n        return None\n    if any(s in name for s in (\'hair\',\'crown\',\'fringe\',\'bun\',\'gathered\',\'wisp\',\'curl\',\'flyaway\',\'fiber\')):\n        return \'hair\'\n    if any(s in name for s in (\'head\',\'ear\',\'neck\',\'palm\',\'finger\',\'thumb\')):\n        return \'skin\'\n    if any(s in name for s in (\'hood\',\'sleeve\',\'cuff\',\'kangaroo\',\'pocket_slanted\',\'pocket_lower\',\'lining\',\'drawstring\')):\n        return \'hoodie\'\n    if any(s in name for s in (\'cargo\',\'trouser\',\'leg_outer\',\'tread\')):\n        return \'trousers\'\n    if any(s in name for s in (\'backpack\',\'shoulder_strap\',\'strap_\')):\n        return \'backpack\'\n    if name.startswith(\'boot_\'):\n        return \'boots\'\n    return None\n\n\ndef _register_uvs(obj, category):\n    data=obj.data\n    uv_layers=[]\n    for name in (\'MiaReferenceFront\',\'MiaReferenceSide\',\'MiaReferenceBack\'):\n        uv_layers.append(data.uv_layers.get(name) or data.uv_layers.new(name=name))\n    attr=data.color_attributes.get(\'MiaReferenceWeights\') or data.color_attributes.new(name=\'MiaReferenceWeights\',type=\'FLOAT_COLOR\',domain=\'POINT\')\n    for vertex in data.vertices:\n        normal=vertex.normal\n        weights=[max(-normal.y,0)**2.5,abs(normal.x)**2.5,max(normal.y,0)**2.5]\n        total=sum(weights)\n        if total<.001:\n            weights=[1.,0.,0.] if vertex.co.y<0 else [0.,0.,1.]\n            total=1.\n        attr.data[vertex.index].color=tuple(w/total for w in weights)+(1.,)\n    for poly in data.polygons:\n        for loop_id in poly.loop_indices:\n            x,y,z=data.vertices[data.loops[loop_id].vertex_index].co\n            sx=87.5 if category==\'skin\' and z>2.60 else 107.5\n            # Front: girl leftmost; side: girl middle faces toward picture right.\n            # Back is mirrored in X by camera orientation, not by image reversal.\n            us=(138+sx*x,355-107.5*y,600-107.5*x)\n            v=1-(964-107.5*z)/1536\n            for idx,layer in enumerate(uv_layers):layer.data[loop_id].uv=(us[idx]/710,v)\n\n\ndef apply_reference_projection(objects, reference_image, strength=.38):\n    """Assign modest three-view albedo paint; return truthful application counts.\n\n    Args:\n        objects: Static mesh objects whose coordinates are already world-space.\n        reference_image: Packed approved reference Blender Image, 710 by 1536.\n        strength: Maximum blend with procedural albedo (never emission).\n    """\n    if tuple(reference_image.size)!=(710,1536):\n        raise ValueError(\'Reference projection requires canonical 710x1536 reference\')\n    strength=max(0,min(float(strength),.65))\n    counts={}; skipped=0; cached={}\n    for obj in objects:\n        if obj.type!=\'MESH\':continue\n        category=_category(obj)\n        if category is None or not obj.data.materials:\n            skipped+=1;continue\n        _register_uvs(obj,category)\n        original_material=obj.data.materials[0]\n        cache_key=(original_material.as_pointer(),category)\n        if cache_key in cached:\n            obj.data.materials[0]=cached[cache_key]\n            obj[\'reference_projection\']=\'three_view_albedo_paint_not_geometry_reconstruction\'\n            counts[category]=counts.get(category,0)+1\n            continue\n        mat=original_material.copy();mat.name=original_material.name+\'_ReferencePaint\'\n        cached[cache_key]=mat\n        obj.data.materials[0]=mat;tree=mat.node_tree\n        bsdf=tree.nodes.get(\'Principled BSDF\')\n        base=bsdf.inputs[\'Base Color\']\n        if base.is_linked:\n            original=base.links[0].from_socket\n            tree.links.remove(base.links[0])\n        else:\n            rgb=tree.nodes.new(\'ShaderNodeRGB\');rgb.outputs[0].default_value=base.default_value\n            original=rgb.outputs[0]\n        weights=tree.nodes.new(\'ShaderNodeVertexColor\');weights.layer_name=\'MiaReferenceWeights\'\n        channels=tree.nodes.new(\'ShaderNodeSeparateColor\');channels.mode=\'RGB\'\n        tree.links.new(weights.outputs[\'Color\'],channels.inputs[\'Color\'])\n        colors=[];validweights=[]\n        for k,uv_name in enumerate((\'MiaReferenceFront\',\'MiaReferenceSide\',\'MiaReferenceBack\')):\n            uv=tree.nodes.new(\'ShaderNodeUVMap\');uv.uv_map=uv_name\n            texture=tree.nodes.new(\'ShaderNodeTexImage\');texture.image=reference_image\n            texture.interpolation=\'Linear\';texture.extension=\'CLIP\'\n            tree.links.new(uv.outputs[\'UV\'],texture.inputs[\'Vector\'])\n            separate=tree.nodes.new(\'ShaderNodeSeparateColor\');separate.mode=\'RGB\'\n            tree.links.new(texture.outputs[\'Color\'],separate.inputs[\'Color\'])\n            red,green,blue=(separate.outputs[i] for i in range(3))\n            maximum=_math(tree,\'MAXIMUM\',_math(tree,\'MAXIMUM\',red,green),blue)\n            minimum=_math(tree,\'MINIMUM\',_math(tree,\'MINIMUM\',red,green),blue)\n            chroma=_math(tree,\'SUBTRACT\',maximum,minimum)\n            # The source gray backdrop has near-zero chroma. Feather its boundary.\n            mask=_math(tree,\'MULTIPLY\',_math(tree,\'SUBTRACT\',chroma,.018),18.)\n            mask=_math(tree,\'MINIMUM\',_math(tree,\'MAXIMUM\',mask,0.),1.)\n            # Category color gates prevent nearby yellow straps being painted as\n            # skin, or face pixels being painted onto front-side hair edges.\n            if category==\'hoodie\':\n                mask=_math(tree,\'MULTIPLY\',mask,_math(tree,\'GREATER_THAN\',blue,red))\n            elif category in (\'hair\',\'trousers\',\'boots\'):\n                warm=_math(tree,\'GREATER_THAN\',red,_math(tree,\'MULTIPLY\',green,1.12))\n                dark=_math(tree,\'LESS_THAN\',maximum,.52 if category==\'hair\' else .66)\n                mask=_math(tree,\'MULTIPLY\',mask,_math(tree,\'MULTIPLY\',warm,dark))\n            elif category==\'skin\':\n                warm=_math(tree,\'GREATER_THAN\',red,_math(tree,\'MULTIPLY\',green,1.14))\n                lit=_math(tree,\'GREATER_THAN\',maximum,.23)\n                mask=_math(tree,\'MULTIPLY\',mask,_math(tree,\'MULTIPLY\',warm,lit))\n            valid=_math(tree,\'MULTIPLY\',channels.outputs[k],mask)\n            validweights.append(valid)\n            gain=.68 if category==\'skin\' else .82\n            color=_vec(tree,\'MULTIPLY\',texture.outputs[\'Color\'],(gain,gain,gain))\n            combine=tree.nodes.new(\'ShaderNodeCombineXYZ\')\n            for inp in combine.inputs:tree.links.new(valid,inp)\n            colors.append(_vec(tree,\'MULTIPLY\',color,combine.outputs[0]))\n        total=_math(tree,\'ADD\',_math(tree,\'ADD\',validweights[0],validweights[1]),validweights[2])\n        reciprocal=_math(tree,\'DIVIDE\',1.,_math(tree,\'MAXIMUM\',total,.0001))\n        combine=tree.nodes.new(\'ShaderNodeCombineXYZ\')\n        for inp in combine.inputs:tree.links.new(reciprocal,inp)\n        painted=_vec(tree,\'MULTIPLY\',_vec(tree,\'ADD\',_vec(tree,\'ADD\',colors[0],colors[1]),colors[2]),combine.outputs[0])\n        mix=tree.nodes.new(\'ShaderNodeMixRGB\');mix.blend_type=\'MIX\'\n        # A full paint weight could project baked features twice. Keep geometry\n        # dominant and attenuate where the source category mask is uncertain.\n        tree.links.new(_math(tree,\'MULTIPLY\',total,strength),mix.inputs[0])\n        tree.links.new(original,mix.inputs[1]);tree.links.new(painted,mix.inputs[2])\n        tree.links.new(mix.outputs[0],base)\n        obj[\'reference_projection\']=\'three_view_albedo_paint_not_geometry_reconstruction\'\n        counts[category]=counts.get(category,0)+1\n    return {\'projection_method\':\'three_view_uv_albedo_paint\',\'strength\':strength,\'painted_mesh_counts\':counts,\n            \'skipped_mesh_count\':skipped,\'geometry_reconstructed\':False,\n            \'limitations\':[\'Reference contains baked illumination\',\'Projection alignment is approximate\',\'Occluded surface detail inferred from side views\',\'Identity requires visual review\']}\n\nif __name__==\'__main__\':\n    run()\n'
