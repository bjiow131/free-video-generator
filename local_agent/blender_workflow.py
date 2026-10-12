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
hair=mat("Mia | light brown hair",(0.36,0.20,0.10))
jacket=mat("Mia | teal-blue jacket",(0.035,0.32,0.40))
pants=mat("Mia | brown trousers",(0.24,0.13,0.075))
backpack=mat("Mia | mustard-yellow backpack",(0.78,0.48,0.055))
helmet=mat("Mia | riding helmet",(0.92,0.67,0.08))
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
# Simple helmet and backpack are continuity blockout cues, not final models.
uv("Mia | riding helmet",(0,-0.005,3.76),(0.51,0.48,0.16),helmet)
uv("Mia | mustard backpack",(0,0.32,2.31),(0.27,0.16,0.34),backpack)
uv("Mia | fringe left",(-0.24,-0.405,3.43),(0.25,0.12,0.19),hair)
uv("Mia | fringe right",(0.08,-0.425,3.45),(0.24,0.11,0.17),hair)
for x in (-0.19,0.19):
    uv("Mia | eye white",(x,-0.438,3.17),(0.09,0.045,0.105),white,20,12)
    uv("Mia | iris",(x,-0.478,3.16),(0.044,0.022,0.058),iris,16,10)
uv("Mia | nose",(0,-0.49,3.02),(0.045,0.04,0.05),skin,16,10)
uv("Mia | jacket torso",(0,0,2.22),(0.37,0.29,0.57),jacket)
uv("Mia | neck",(0,0,2.77),(0.13,0.13,0.17),skin)
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
            if any(w in label for w in ("head","hair","fringe","eye","iris","nose","helmet")): bone="head"
            elif "neck" in label: bone="neck"
            elif any(w in label for w in ("backpack","torso")): bone="spine"
            elif "sleeve" in label: bone="upper_arm"+side
            elif any(w in label for w in ("cuff","hand")): bone="forearm"+side
            elif "trouser leg" in label: bone="thigh"+side
            elif any(w in label for w in ("trouser cuff","shoe")): bone="shin"+side
        else:
            if "body" in label or "shell" in label: bone="body"
            elif "head" in label: bone="head"
            elif "stalk" in label or "eye" in label:
                bone="eye.L" if relative_x<0.34 else "eye.R"
        if bone not in data.bones:
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
    ("upper_arm.L",(0.30,0,2.25),(0.62,0,1.93),"spine"),
    ("forearm.L",(0.62,0,1.93),(0.78,0,1.60),"upper_arm.L"),
    ("upper_arm.R",(-0.30,0,2.25),(-0.62,0,1.93),"spine"),
    ("forearm.R",(-0.62,0,1.93),(-0.78,0,1.60),"upper_arm.R"),
    ("thigh.L",(0.18,0,1.48),(0.20,0,0.88),"pelvis"),
    ("shin.L",(0.20,0,0.88),(0.20,0,0.22),"thigh.L"),
    ("thigh.R",(-0.18,0,1.48),(-0.20,0,0.88),"pelvis"),
    ("shin.R",(-0.20,0,0.88),(-0.20,0,0.22),"thigh.R"),
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
import bpy, json, math, os, sys, hashlib
from mathutils import Vector
args=sys.argv[sys.argv.index("--")+1:]
cfg=json.load(open(args[0],encoding="utf-8"))
out=os.path.realpath(cfg["output_dir"])
bpy.ops.wm.open_mainfile(filepath=os.path.join(out,"mia_blockout.blend"),load_ui=False)
scene=bpy.context.scene
scene.frame_start=1; scene.frame_end=720; scene.render.fps=12
scene.render.resolution_x=720; scene.render.resolution_y=1280; scene.render.resolution_percentage=100
scene.render.image_settings.file_format="PNG"
scene.render.filepath=os.path.join(out,"preview.png")
def aim(camera, point):
    camera.rotation_euler=(Vector(point)-camera.location).to_track_quat("-Z","Y").to_euler()
camera=scene.camera
camera.data.type="ORTHO"; camera.data.ortho_scale=9.5
camera.location=(-0.25,-12.5,4.7); aim(camera,(-0.25,0.1,1.85))
helmet=bpy.data.objects.get("Mia | riding helmet")
backpack=bpy.data.objects.get("Mia | mustard backpack")
if not helmet or not backpack: raise RuntimeError("Mia helmet/backpack proxy is missing")
def material(name, rgba):
    m=bpy.data.materials.get(name)
    if m is None:
        m=bpy.data.materials.new(name); m.diffuse_color=rgba; m.use_nodes=True
        bs=m.node_tree.nodes.get("Principled BSDF")
        if bs: bs.inputs["Base Color"].default_value=rgba
    return m
gold=material("Mia | mustard strap",(0.90,0.56,0.08,1))
dark=material("Mia | helmet strap",(0.12,0.11,0.09,1))
def bar(name,a,b,r,mat):
    vec=Vector(b)-Vector(a); mid=(Vector(a)+Vector(b))*0.5
    bpy.ops.mesh.primitive_cylinder_add(vertices=12,radius=r,depth=vec.length,location=mid)
    o=bpy.context.object; o.name=name; o.data.materials.append(mat)
    o.rotation_euler=vec.to_track_quat("Z","Y").to_euler(); return o
for sign in (-1,1):
    bar("Mia | visible backpack shoulder strap",(sign*0.25,-0.31,2.56),(sign*0.19,-0.31,2.05),0.055,gold)
    bar("Mia | helmet chin strap",(sign*0.39,-0.30,3.69),(0,-0.35,2.90),0.025,dark)
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
mouth_mat=material("Face | mouth",(0.055,0.018,0.014,1))
def mouth_for(prefix,x,y,z):
    return sphere(prefix+" | mouth cue",(x,y,z),(0.105,0.025,0.025),mouth_mat)
mia_mouth=mouth_for("Mia",0,-0.475,2.96)
step_mouth=mouth_for("Stepa",-2.05,-0.47,2.96)
def animate_mouth(obj, intervals):
    for start,end in intervals:
        for frame,scale in ((start,(1,1,0.15)),(start+3,(1,1,1)),(end-3,(1,1,1)),(end,(1,1,0.15))):
            obj.scale=scale; obj.keyframe_insert(data_path="scale",frame=frame)
    if obj.animation_data and obj.animation_data.action:
        for fc in obj.animation_data.action.fcurves:
            for key in fc.keyframe_points: key.interpolation="CONSTANT"
animate_mouth(step_mouth,[(20,125),(270,330),(390,475)])
animate_mouth(mia_mouth,[(130,255),(340,385),(485,545)])
def parent_group(prefixes,name):
    root=bpy.data.objects.new(name,None); scene.collection.objects.link(root)
    root.empty_display_type="PLAIN_AXES"; root.empty_display_size=0.5
    for obj in list(scene.objects):
        if any(obj.name.startswith(prefix) for prefix in prefixes) or obj.name in ("Mia_Rig","Stepa_Rig"):
            if obj is root: continue
            world=obj.matrix_world.copy(); obj.parent=root; obj.matrix_world=world
    return root
mia_root=parent_group(("Mia |","Scooter |"),"Mia_Root_animated")
step_root=parent_group(("Stepa |",),"Stepa_Root_animated")
for frame,x in ((1,0),(480,0),(540,0.25),(600,0.5),(720,0.5)):
    mia_root.location.x=x; mia_root.keyframe_insert(data_path="location",frame=frame)
for frame,tilt in ((1,0),(90,0),(120,0.06),(150,0),(300,0),(340,-0.05),(380,0),(720,0)):
    step_root.rotation_euler.z=tilt; step_root.keyframe_insert(data_path="rotation_euler",frame=frame)
for obj in scene.objects:
    if obj.name=="Scooter | wheel":
        for frame,angle in ((1,0),(480,0),(600,-math.pi*2),(720,-math.pi*2)):
            obj.rotation_euler.y=angle; obj.keyframe_insert(data_path="rotation_euler",frame=frame)
for frame,loc,scale in ((1,(-0.25,-12.5,4.7),9.5),(180,(-0.25,-12.3,4.6),9.5),
                        (360,(-0.25,-11.8,4.4),9.2),(540,(-0.25,-11.5,4.2),9.0),
                        (720,(-0.25,-12.0,4.4),9.5)):
    camera.location=loc; camera.data.ortho_scale=scale; aim(camera,(-0.25,0.1,1.85))
    camera.keyframe_insert(data_path="location",frame=frame)
    camera.keyframe_insert(data_path="rotation_euler",frame=frame)
    camera.data.keyframe_insert(data_path="ortho_scale",frame=frame)
asset_root=os.path.realpath(cfg["asset_root"])
ref_meta={}
for key,rel in (("mia_passport","characters/passports/mia.json"),
                ("stepa_passport","characters/passports/stepa.json"),
                ("draft_board","references/episode-01-reference-board.png")):
    path=os.path.realpath(os.path.join(asset_root,rel))
    if os.path.commonpath((asset_root,path))!=asset_root or not os.path.isfile(path):
        raise RuntimeError("Required pinned Episode 1 reference asset is missing")
    with open(path,"rb") as f: raw=f.read()
    ref_meta[key]={"relative_path":rel,"sha256":hashlib.sha256(raw).hexdigest()}
    if key.endswith("passport"):
        data=json.loads(raw.decode("utf-8"))
        if data.get("status")!="awaiting_original_references":
            raise RuntimeError("Unexpected passport status")
    else:
        image=bpy.data.images.load(path,check_existing=True); image.pack()
        empty=bpy.data.objects.new("REFERENCE ONLY | generated draft board",None)
        scene.collection.objects.link(empty); empty.empty_display_type="IMAGE"; empty.data=image
        empty.location=(100,100,0); empty.hide_render=True; empty["status"]="draft_not_approved"
scene["episode_id"]="S01E01"; scene["scene_id"]="S01_SC01"
scene["asset_status"]="procedural proxies; passports verified; generated board is draft"
scene["reference_sha256_json"]=json.dumps(ref_meta,sort_keys=True)
scene["audio_policy"]="silent; no voice, music, or subtitles"
scene.frame_set(1)
scene.render.image_settings.file_format="PNG"
scene.render.filepath=os.path.join(out,"preview.png")
bpy.ops.render.render(write_still=True)
scene.render.image_settings.file_format="FFMPEG"
scene.render.ffmpeg.format="MPEG4"; scene.render.ffmpeg.codec="H264"
scene.render.ffmpeg.constant_rate_factor="MEDIUM"; scene.render.ffmpeg.video_bitrate=2500
scene.render.ffmpeg.audio_codec="NONE"
scene.render.filepath=os.path.join(out,"scene")
blend=os.path.join(out,"mia_blockout.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend)
bpy.ops.render.render(animation=True)
video=os.path.join(out,"scene.mp4")
if not os.path.isfile(video) or os.path.getsize(video)<1024:
    raise RuntimeError("Silent MP4 render is missing or empty")
with open(os.path.join(out,"blender_result.json"),"w",encoding="utf-8") as f:
    json.dump({"status":"completed","stage":"episode1_scene1_animated_animatic",
               "blend_path":blend,"preview_path":os.path.join(out,"preview.png"),
               "video_path":video,"duration_seconds":60,"fps":12,"frame_count":720,
               "object_count":len(scene.objects),"audio":"none","subtitles":"none",
               "asset_provenance":ref_meta,"production_models_available":False,
               "manual_visual_review_required":True},f,ensure_ascii=False)
'''


def _render_episode1_release(project: Path, workspace: Path, blender: Path) -> dict[str, Any]:
    """Render only the fixed Episode 1 scene folder; never overwrite existing files."""
    if project.name != "S01E01_SC01_RELEASE":
        return {"status": "rejected", "reason": "episode1_release_project_not_allowlisted"}
    asset_root = workspace / "episode1" / "assets"
    required = [
        asset_root / "characters" / "passports" / "mia.json",
        asset_root / "characters" / "passports" / "stepa.json",
        asset_root / "references" / "episode-01-reference-board.png",
    ]
    if any(is_link_or_junction(p) or not p.is_file() for p in required):
        return {"status": "blocked", "reason": "pinned_episode1_reference_assets_missing"}
    if (project / "scene.mp4").exists():
        return {"status": "blocked", "reason": "release_video_exists_no_overwrite"}
    import tempfile
    with tempfile.TemporaryDirectory(prefix=".mia-release-", dir=project) as temp:
        script = Path(temp) / "episode1_animation.py"
        cfg = Path(temp) / "release.json"
        script.write_text(_episode1_animation_script(), encoding="utf-8")
        cfg.write_text(json.dumps({"output_dir": str(project), "asset_root": str(asset_root)},
                                  ensure_ascii=False), encoding="utf-8")
        try:
            proc = subprocess.run(
                [str(blender), "--background", "--disable-autoexec", "--offline-mode",
                 "--python-exit-code", "1", "--python", str(script), "--", str(cfg)],
                cwd=str(project), capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=2400, check=False, shell=False,
            )
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "reason": "episode1_animation_render_timeout"}
        except OSError as exc:
            return {"status": "error", "error_type": type(exc).__name__}
    if proc.returncode != 0:
        return {"status": "failed", "reason": "episode1_animation_render_failed",
                "return_code": proc.returncode, "stderr_tail": (proc.stderr or "")[-2500:]}
    manifest = project / "blender_result.json"
    blend = project / "mia_blockout.blend"
    preview = project / "preview.png"
    video = project / "scene.mp4"
    if any(is_link_or_junction(p) or not p.is_file() or p.stat().st_size == 0
           for p in (manifest, blend, preview, video)):
        return {"status": "failed", "reason": "episode1_release_output_missing"}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "failed", "reason": "episode1_release_manifest_invalid"}
    png_ok, png_reason, dimensions = _validate_png(preview, (720, 1280))
    if not png_ok:
        return {"status": "failed", "reason": png_reason}
    if (data.get("status") != "completed" or data.get("stage") != "episode1_scene1_animated_animatic"
            or data.get("duration_seconds") != 60 or data.get("frame_count") != 720
            or data.get("audio") != "none" or data.get("subtitles") != "none"):
        return {"status": "failed", "reason": "episode1_release_manifest_validation_failed"}
    with video.open("rb") as stream: header = stream.read(16)
    if b"ftyp" not in header or video.stat().st_size > 32_000_000:
        return {"status": "failed", "reason": "episode1_release_video_invalid_or_too_large"}
    return {"status": "completed", "task": "blender_mia_blockout",
            "stage": data["stage"], "project_dir": str(project),
            "blend_path": str(blend), "preview_path": str(preview),
            "video_path": str(video), "resolution": dimensions,
            "duration_seconds": 60, "fps": 12, "frame_count": 720,
            "object_count": data.get("object_count"), "manual_review_required": True,
            "note": "Silent procedural animatic; concept board remains a draft and production models are not approved."}


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
    if project_name == "S01E01_SC01_RELEASE":
        outputs.append(project / "scene.mp4")
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
            result = _render_episode1_release(project, workspace, blender)
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
