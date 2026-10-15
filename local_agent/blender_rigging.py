"""Bounded Blender rig prototype for an existing Mia blockout project.

Creates a separate .blend output with rigid per-part proxy weights; not production skinning.
"""
from __future__ import annotations
from local_agent.path_names import path_identifier_pattern, is_link_or_junction

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any
from local_agent.blender_locator import (
    find_blender_executable, is_supported_windows_blender,
    watch_unsupported_blender_dialogs,
)

_REAL_SUBPROCESS_RUN = subprocess.run


PROJECT_RE = path_identifier_pattern(48)

_RIG_SCRIPT = r'''
import bpy, json, os, sys
args = sys.argv[sys.argv.index("--") + 1:]
source_path, output_path, report_path = [os.path.realpath(x) for x in args]
bpy.ops.wm.open_mainfile(filepath=source_path, load_ui=False)
arm_data = bpy.data.armatures.new("Mia_Rig")
arm = bpy.data.objects.new("Mia_Rig", arm_data)
bpy.context.scene.collection.objects.link(arm)
bpy.ops.object.select_all(action="DESELECT")
bpy.context.view_layer.objects.active = arm
arm.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
bones = [
    ("root", (0,0,0.15), (0,0,0.55), None),
    ("pelvis", (0,0,1.45), (0,0,1.78), "root"),
    ("spine", (0,0,1.78), (0,0,2.35), "pelvis"),
    ("neck", (0,0,2.35), (0,0,2.65), "spine"),
    ("head", (0,0,2.65), (0,0,3.35), "neck"),
    ("upper_arm.L", (0.30,0,2.25), (0.62,0,1.93), "spine"),
    ("forearm.L", (0.62,0,1.93), (0.78,0,1.60), "upper_arm.L"),
    ("upper_arm.R", (-0.30,0,2.25), (-0.62,0,1.93), "spine"),
    ("forearm.R", (-0.62,0,1.93), (-0.78,0,1.60), "upper_arm.R"),
    ("thigh.L", (0.18,0,1.48), (0.20,0,0.88), "pelvis"),
    ("shin.L", (0.20,0,0.88), (0.20,0,0.22), "thigh.L"),
    ("thigh.R", (-0.18,0,1.48), (-0.20,0,0.88), "pelvis"),
    ("shin.R", (-0.20,0,0.88), (-0.20,0,0.22), "thigh.R"),
]
made = {}
for name, head, tail, parent in bones:
    b = arm_data.edit_bones.new(name)
    b.head, b.tail = head, tail
    made[name] = b
for name, head, tail, parent in bones:
    if parent:
        made[name].parent = made[parent]
        made[name].use_connect = False
bpy.ops.object.mode_set(mode="OBJECT")
arm.show_in_front = True
arm_data.display_type = "OCTAHEDRAL"
# Bind Mia's separate proxy parts rigidly to matching bones. This is not
# smooth skinning; it lets the blockout test articulated pose changes.
bound_objects = []
unbound_objects = []
for obj in list(bpy.context.scene.objects):
    if obj.type != "MESH" or not obj.name.startswith("Mia |"):
        continue
    label = obj.name.lower()
    x = obj.matrix_world.translation.x
    side = ".L" if x >= 0 else ".R"
    bone_name = None
    if any(word in label for word in ("head", "hair", "fringe", "eye", "iris", "nose", "helmet")):
        bone_name = "head"
    elif "neck" in label:
        bone_name = "neck"
    elif "backpack" in label or "torso" in label:
        bone_name = "spine"
    elif "sleeve" in label or "upper arm" in label:
        bone_name = "upper_arm" + side
    elif "cuff" in label or "forearm" in label or "hand" in label:
        bone_name = "forearm" + side
    elif "lower leg" in label or "trouser cuff" in label or "shoe" in label:
        bone_name = "shin" + side
    elif "trouser leg" in label or "leg" in label:
        bone_name = "thigh" + side
    if bone_name is None or bone_name not in arm_data.bones:
        unbound_objects.append(obj.name)
        continue
    group = obj.vertex_groups.new(name=bone_name)
    if len(obj.data.vertices):
        group.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
    modifier = obj.modifiers.new(name="Mia rigid bone binding", type="ARMATURE")
    modifier.object = arm
    bound_objects.append({"object": obj.name, "bone": bone_name})
# Smoke-test a small forearm rotation, then reset the pose before saving.
bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="POSE")
pose = arm.pose.bones["forearm.L"]
pose.rotation_mode = "XYZ"
pose.rotation_euler[1] = 0.18
bpy.context.view_layer.update()
pose.rotation_euler = (0.0, 0.0, 0.0)
bpy.context.view_layer.update()
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.wm.save_as_mainfile(filepath=output_path)
report = {
    "status": "completed",
    "stage": "rigged_proxy_smoke_test",
    "source_path": source_path,
    "output_path": output_path,
    "armature": arm.name,
    "bone_count": len(arm_data.bones),
    "pose_smoke_test": "passed_and_reset",
    "mesh_binding": "rigid_per_part_weights",
    "bound_object_count": len(bound_objects),
    "unbound_objects": unbound_objects,
    "bound_objects": bound_objects,
}
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False)
'''


def create_mia_skeleton(project_name: str) -> dict[str, Any]:
    """Create a separate skeleton prototype without overwriting the blockout."""
    if not isinstance(project_name, str) or not PROJECT_RE.fullmatch(project_name):
        return {"status": "rejected", "reason": "invalid_project_name"}
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not workspace_value:
        return {"status": "blocked", "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally"}
    blender = find_blender_executable()
    if blender is None:
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    if os.name == "nt" and subprocess.run is _REAL_SUBPROCESS_RUN and not is_supported_windows_blender(blender):
        return {"status": "blocked", "reason": "blender_executable_not_supported_64_bit_windows"}
    workspace = Path(workspace_value).expanduser().resolve()
    project = workspace / project_name
    if is_link_or_junction(project):
        return {"status": "rejected", "reason": "project_must_not_be_symlink_or_junction"}
    project = project.resolve()
    if not project.is_relative_to(workspace) or project == workspace:
        return {"status": "rejected", "reason": "project_outside_workspace"}
    if is_link_or_junction(project):
        return {"status": "rejected", "reason": "project_must_not_be_symlink_or_junction"}
    source = project / "mia_blockout.blend"
    if is_link_or_junction(source):
        return {"status": "rejected", "reason": "output_path_must_not_be_symlink_or_junction"}
    if not source.is_file() or source.stat().st_size == 0:
        return {"status": "blocked", "reason": "mia_blockout_project_not_found"}
    output = project / "mia_skeleton.blend"
    report = project / "mia_skeleton_result.json"
    if is_link_or_junction(output) or is_link_or_junction(report):
        return {"status": "rejected", "reason": "output_path_must_not_be_symlink_or_junction"}
    if output.exists() or report.exists():
        return {"status": "blocked", "reason": "skeleton_outputs_exist_no_overwrite"}
    for path in (source, output, report):
        if is_link_or_junction(path):
            return {"status": "rejected", "reason": "output_path_must_not_be_symlink_or_junction"}
    try:
        with tempfile.TemporaryDirectory(prefix=".mia-rig-", dir=project) as temp:
            script = Path(temp) / "skeleton.py"
            script.write_text(_RIG_SCRIPT, encoding="utf-8")
            dismissed_dialogs: list[dict[str, object]] = []
            with watch_unsupported_blender_dialogs(blender, dismissed_dialogs):
                proc = subprocess.run(
                    [str(blender), "--disable-autoexec", "--background", "--factory-startup",
                     "--python-exit-code", "1", "--python", str(script), "--", str(source), str(output), str(report)],
                    cwd=str(project), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                    check=False, shell=False,
                )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "skeleton_smoke_test_timeout"}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__,
                "compatibility_dialog_auto_closed": bool(locals().get("dismissed_dialogs"))}
    if proc.returncode != 0 or not output.is_file() or output.stat().st_size == 0 or not report.is_file():
        return {"status": "failed", "reason": "blender_skeleton_step_failed",
                "return_code": proc.returncode, "stderr_tail": (proc.stderr or "")[-2000:],
                "compatibility_dialog_auto_closed": bool(dismissed_dialogs)}
    try:
        result = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "failed", "reason": "skeleton_report_unreadable"}
    if not isinstance(result, dict) or result.get("status") != "completed" or result.get("stage") != "rigged_proxy_smoke_test" or result.get("bone_count") != 13 or result.get("pose_smoke_test") != "passed_and_reset" or result.get("bound_object_count", 0) < 1:
        return {"status": "failed", "reason": "skeleton_report_validation_failed"}
    return {
        "status": "completed", "task": "blender_mia_skeleton",
        "blend_path": str(output), "bone_count": result["bone_count"],
        "pose_smoke_test": result["pose_smoke_test"],
        "mesh_binding": "rigid_per_part_weights",
        "bound_object_count": result["bound_object_count"],
        "unbound_objects": result["unbound_objects"],
        "note": "Proxy parts follow bones rigidly; this is not smooth production skinning and needs visual validation.",
    }


# Added for the bounded Spring full-rig transfer pilot.
SPRING_TRANSFER_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
SPRING_TRANSFER_ARCHIVE_URL = "https://studio.blender.org/download-source/files/1b/1bffff08b464375d842e7da43b4f5293/1bffff08b464375d842e7da43b4f5293.zip"
SPRING_TRANSFER_ARCHIVE_SHA256 = "4574b8161f517f0c6ca02af9f5eeded307a26d7015bd71f66bd55bea9173b2cd"
SPRING_TRANSFER_BLEND_SHA256 = "8005f5cedb70faccd5557e6b0b001662f8681436f761d1f83e64feb9e02f0502"

SPRING_TRANSFER_SCRIPT = r'''
import bpy, json, os, sys
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree
donor_path,source_mia_path,out_path,report_path=[os.path.realpath(p) for p in sys.argv[sys.argv.index("--")+1:]]
bpy.ops.wm.open_mainfile(filepath=source_mia_path,load_ui=False)
scene=bpy.context.scene
mia=[o for o in scene.objects if o.type=="MESH" and o.name.lower() not in {"studio_floor","stage_ground","ground"}]
if not mia or sum(len(o.data.vertices) for o in mia)<1000: raise RuntimeError("expected Mia meshes were not found")
# Replace only the lightweight adaptation pilot; preserve mesh data, shape keys,
# materials, and all non-armature modifiers from the polished source.
pilot=bpy.data.objects.get("Mia_Source_Pilot_Rig")
pilot_names={b.name for b in pilot.data.bones} if pilot else set()
for obj in mia:
    # The imported Spring rig is the sole deformation stack in the output.
    for mod in list(obj.modifiers):
        if mod.type=="ARMATURE": obj.modifiers.remove(mod)
    for name in pilot_names:
        group=obj.vertex_groups.get(name)
        if group: obj.vertex_groups.remove(group)
if pilot: bpy.data.objects.remove(pilot,do_unlink=True)
with bpy.data.libraries.load(donor_path,link=False) as (src,dst):
    names=list(src.objects); dst.objects=names; dst.texts=list(src.texts)
spring=[o for o in dst.objects if o]
rig=next((o for o in spring if o.type=="ARMATURE" and len(o.data.bones)>=2000),None)
if len(spring)<100 or rig is None: raise RuntimeError("full Spring rig did not append")
# A source may already contain its original Spring armature under the same name.
# Keep it out of view; the appended, checksum-pinned donor above drives Mia.
col=bpy.data.collections.new("Spring rig transfer dependencies"); scene.collection.children.link(col)
spring_set=set(spring)
for o in spring:
    if col.name not in {c.name for c in o.users_collection}: col.objects.link(o)
points=[o.matrix_world@v.co for o in mia for v in o.data.vertices]
zlo=min(p.z for p in points); zhi=max(p.z for p in points)
xmid=(min(p.x for p in points)+max(p.x for p in points))*0.5
ymid=(min(p.y for p in points)+max(p.y for p in points))*0.5
deform=[b for b in rig.data.bones if b.use_deform]
srcz=[(rig.matrix_world@b.head_local).z for b in deform]+[(rig.matrix_world@b.tail_local).z for b in deform]
scale=(zhi-zlo)/(max(srcz)-min(srcz))
root=bpy.data.objects.new("Spring rig fit scale",None); col.objects.link(root)
root.location=(xmid,ymid,zlo); root.scale=(scale,scale,scale)
old_world={o:o.matrix_world.copy() for o in spring if o.parent not in spring_set}
for o,m in old_world.items():
    o.parent=root; o.matrix_parent_inverse=Matrix.Identity(4); o.matrix_basis=m
for o in spring:
    if o.type=="MESH": o.hide_render=True; o.hide_set(True)
for existing in scene.objects:
    if existing.type=="ARMATURE" and existing is not rig:
        existing.hide_render=True; existing.hide_set(True)
rig.hide_render=True; rig.show_in_front=True
bpy.context.view_layer.update()
def segdist(p,a,b):
    d=b-a; den=d.length_squared
    t=0.0 if den<1e-12 else max(0.0,min(1.0,(p-a).dot(d)/den))
    return (p-(a+d*t)).length
def words(name):
    n=name.lower()
    if any(x in n for x in ("head","face","eye","iris","brow","nose","mouth","lip","ear","hair","fringe","bun")): return ("head","eye","brow","nose","cheek","jaw","lip","mouth","hair","ear")
    if any(x in n for x in ("arm","sleeve","hand","cuff")): return ("arm","forearm","elbow","hand","wrist","shoulder","sleeve")
    if any(x in n for x in ("leg","boot","shoe","foot")): return ("thigh","knee","shin","foot","ankle","leg")
    if any(x in n for x in ("torso","body","jacket","hood","backpack","shirt","sweater","coat")): return ("spine","chest","torso","waist","hip","pelvis","body")
    return ()
def sample_eval(obj):
    dg=bpy.context.evaluated_depsgraph_get(); ev=obj.evaluated_get(dg); me=ev.to_mesh()
    result=[ev.matrix_world@me.vertices[i].co for i in range(0,len(me.vertices),max(1,len(me.vertices)//800))]
    ev.to_mesh_clear(); return result
bound=[]; unbound=[]; assignments=0
for obj in mia:
    keys=words(obj.name); candidates=[b for b in deform if not keys or any(k in b.name.lower() for k in keys)]
    if not candidates: candidates=deform
    tree=KDTree(3*len(candidates)); seg=[]
    for i,b in enumerate(candidates):
        a=rig.matrix_world@b.head_local; z=rig.matrix_world@b.tail_local; seg.append((b.name,a,z))
        for j,p in enumerate((a,(a+z)*0.5,z)): tree.insert(p,3*i+j)
    tree.balance(); buckets={}; ngroups=set()
    for vi,v in enumerate(obj.data.vertices):
        p=obj.matrix_world@v.co; near=tree.find_n(p,min(24,3*len(candidates))); ids=[]
        for _,idx,_ in near:
            k=idx//3
            if k not in ids: ids.append(k)
        scores=sorted(((segdist(p,seg[k][1],seg[k][2]),seg[k][0]) for k in ids))[:4]
        raw=[(name,1.0/((d+0.018)*(d+0.018))) for d,name in scores]; total=sum(w for _,w in raw)
        for name,w in raw:
            q=max(1,min(100,round(100*w/total))); buckets.setdefault((name,q),[]).append(vi); ngroups.add(name)
    for (name,q),indices in buckets.items():
        vg=obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name); vg.add(indices,q/100.0,"REPLACE")
    if ngroups:
        mod=obj.modifiers.new("Spring full rig | transferred weights","ARMATURE"); mod.object=rig; mod.use_vertex_groups=True; mod.use_bone_envelopes=False
        obj.modifiers.move(len(obj.modifiers)-1,0); bound.append({"object":obj.name,"vertices":len(obj.data.vertices),"groups":len(ngroups)})
        assignments+=sum(len(v) for v in buckets.values())
    else: unbound.append(obj.name)
if not bound: raise RuntimeError("no Mia meshes received weights")
bpy.context.view_layer.update(); test_obj=next((o for o in mia if any(k in o.name.lower() for k in ("sleeve","forearm","arm"))),max(mia,key=lambda o:len(o.data.vertices))); before=sample_eval(test_obj)
test_name=next((n for n in ("master_torso","master_body","master") if n in rig.pose.bones),None)
max_delta=0.0
if test_name:
    pb=rig.pose.bones[test_name]; pb.rotation_mode="XYZ"; pb.rotation_euler[1]=0.12; bpy.context.view_layer.update(); after=sample_eval(test_obj)
    max_delta=max(((a-b).length for a,b in zip(before,after)),default=0.0); pb.rotation_euler=(0,0,0); bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=out_path)
report={"status":"completed","bone_count":len(rig.data.bones),"deform_bone_count":len(deform),"pose_constraint_count":sum(len(p.constraints) for p in rig.pose.bones),"driver_count":len(rig.animation_data.drivers) if rig.animation_data else 0,"mia_mesh_count":len(mia),"bound_mesh_count":len(bound),"unbound_mesh_count":len(unbound),"vertex_count":sum(x["vertices"] for x in bound),"weight_assignments":assignments,"scale_to_mia_height":scale,"pose_test_bone":test_name,"pose_test_passed":max_delta>1e-5,"max_pose_vertex_displacement":max_delta,"output_blend":out_path,"bound_objects":bound,"unbound_objects":unbound,"limitations":["Proximity weights need visual correction at joints","Separate Mia eye and mouth meshes do not inherit Spring facial topology or shape keys","Spring custom-property setup was preserved but not executed","Blender compatibility and target-PC performance need review"]}
with open(report_path,"w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
'''


def _spring_sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()


def transfer_spring_rig_to_mia(project_name: str) -> dict[str, Any]:
    """Create a separate Spring-rigged copy of the polished Mia source."""
    if not isinstance(project_name, str) or not SPRING_TRANSFER_PROJECT_RE.fullmatch(project_name):
        return {"status": "rejected", "reason": "invalid_project_name"}
    exe = os.environ.get("BLENDER_EXECUTABLE", "").strip()
    root = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not exe or not root:
        return {"status": "blocked", "reason": "local_blender_or_workspace_not_configured"}
    blender = find_blender_executable()
    workspace = Path(root).expanduser().resolve()
    if blender is None or not blender.is_file():
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    if os.name == "nt" and subprocess.run is _REAL_SUBPROCESS_RUN and not is_supported_windows_blender(blender):
        return {"status": "blocked", "reason": "blender_executable_not_supported_64_bit_windows"}

    project = workspace / "SOURCE_ADAPTATIONS" / project_name
    if any(is_link_or_junction(p) for p in (project, project.parent, project.parent.parent)):
        return {"status": "rejected", "reason": "unsafe_project_path"}
    project = project.resolve()
    if not project.is_relative_to(workspace) or project == workspace:
        return {"status": "rejected", "reason": "unsafe_project_path"}
    source_mia = project / "mia_spring_source_adapted.blend"
    output = project / "mia_spring_source_adapted_spring_rig.blend"
    report = project / "spring_rig_transfer_result.json"
    if any(is_link_or_junction(p) for p in (source_mia, output, report)):
        return {"status": "rejected", "reason": "unsafe_project_file"}
    if not source_mia.is_file() or source_mia.stat().st_size == 0:
        return {"status": "blocked", "reason": "polished_mia_source_missing"}
    if output.exists() or report.exists():
        return {"status": "blocked", "reason": "output_exists_no_overwrite"}

    cache = workspace / ".local_agent" / "cache" / "spring-rig-source-v1"
    if is_link_or_junction(cache):
        return {"status": "rejected", "reason": "unsafe_cache_path"}
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / "spring-source.zip"
    donor = cache / "spring" / "spring" / "spring.blend"
    if is_link_or_junction(archive) or is_link_or_junction(donor):
        return {"status": "rejected", "reason": "unsafe_cache_file"}
    if not donor.is_file() or _spring_sha256(donor) != SPRING_TRANSFER_BLEND_SHA256:
        if not archive.is_file() or _spring_sha256(archive) != SPRING_TRANSFER_ARCHIVE_SHA256:
            temp = None
            try:
                from urllib.request import Request, urlopen
                request = Request(SPRING_TRANSFER_ARCHIVE_URL, headers={"User-Agent": "OctavaLocalAgent/1.0"})
                with urlopen(request, timeout=60) as response, tempfile.NamedTemporaryFile(
                    prefix="spring-", suffix=".tmp", dir=cache, delete=False
                ) as f:
                    temp = Path(f.name)
                    total = 0
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > 500 * 1024 * 1024:
                            raise ValueError("fixed archive size limit exceeded")
                        f.write(chunk)
                if _spring_sha256(temp) != SPRING_TRANSFER_ARCHIVE_SHA256:
                    raise ValueError("archive checksum mismatch")
                os.replace(temp, archive)
            except Exception as exc:
                if temp:
                    temp.unlink(missing_ok=True)
                return {"status": "blocked", "reason": "spring_download_or_checksum_failed",
                        "error_type": type(exc).__name__}
        try:
            import zipfile
            with zipfile.ZipFile(archive) as zf:
                if zf.testzip():
                    raise ValueError("archive CRC failure")
                for member in zf.infolist():
                    parts = Path(member.filename).parts
                    if member.filename.startswith("spring/spring/") and ".." not in parts:
                        zf.extract(member, cache)
        except Exception as exc:
            return {"status": "failed", "reason": "spring_extract_failed",
                    "error_type": type(exc).__name__}
        if not donor.is_file() or _spring_sha256(donor) != SPRING_TRANSFER_BLEND_SHA256:
            return {"status": "failed", "reason": "spring_blend_checksum_mismatch"}

    try:
        with tempfile.TemporaryDirectory(prefix=".spring-rig-", dir=project) as td:
            script = Path(td) / "transfer.py"
            script.write_text(SPRING_TRANSFER_SCRIPT, encoding="utf-8")
            dismissed_dialogs = []
            with watch_unsupported_blender_dialogs(blender, dismissed_dialogs):
                proc = subprocess.run(
                    [str(blender), "--disable-autoexec", "--background", "--factory-startup",
                     "--python-exit-code", "1", "--python", str(script), "--",
                     str(donor), str(source_mia), str(output), str(report)],
                    cwd=str(project), capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=14400, check=False, shell=False,
                )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "transfer_exceeded_4_hours"}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}
    if proc.returncode or not output.is_file() or not report.is_file():
        return {"status": "failed", "reason": "blender_transfer_failed",
                "return_code": proc.returncode, "stderr_tail": (proc.stderr or "")[-2500:]}
    try:
        data = json.loads(report.read_text("utf-8"))
    except (OSError, ValueError):
        return {"status": "failed", "reason": "transfer_report_unreadable"}
    complete = (
        data.get("status") == "completed"
        and data.get("bone_count", 0) >= 2000
        and data.get("bound_mesh_count", 0) == data.get("mia_mesh_count", -1)
        and data.get("unbound_mesh_count") == 0
        and data.get("pose_test_passed") is True
    )
    if not complete:
        return {"status": "incomplete", "reason": "transfer_validation_failed",
                "blend_path": str(output), "report_path": str(report), "transfer": data}
    return {
        "status": "completed", "task": "blender_mia_spring_rig_transfer",
        "blend_path": str(output), "report_path": str(report),
        "bone_count": data["bone_count"], "deform_bone_count": data["deform_bone_count"],
        "pose_test_passed": data["pose_test_passed"],
        "max_pose_vertex_displacement": data["max_pose_vertex_displacement"],
        "bound_mesh_count": data["bound_mesh_count"],
        "unbound_mesh_count": data["unbound_mesh_count"],
        "scale_to_mia_height": data["scale_to_mia_height"],
        "limitations": data["limitations"],
    }

# Fixed, licensed source inventory. No remote task can supply executable code,
# download URLs or filesystem paths.
SOURCE_REVIEW_SCRIPT = r'''
import bpy, sys, json, os, hashlib, struct
from mathutils import Vector
source, report = sys.argv[sys.argv.index('--') + 1:]
bpy.ops.wm.open_mainfile(filepath=source, load_ui=False)
def mesh_info(o):
    h=hashlib.sha256()
    for v in o.data.vertices: h.update(struct.pack('<3f',*v.co))
    coords=[o.matrix_world@v.co for v in o.data.vertices]
    bounds=[[min(p[k] for p in coords),max(p[k] for p in coords)] for k in range(3)] if coords else []
    return {'name':o.name,'vertices':len(o.data.vertices),'polygons':len(o.data.polygons),
        'coordinates_sha256':h.hexdigest(),'bounds_world':bounds,'hidden_render':o.hide_render,
        'materials':[m.name if m else None for m in o.data.materials],
        'shape_keys':[k.name for k in o.data.shape_keys.key_blocks] if o.data.shape_keys else [],
        'modifiers':[{'name':m.name,'type':m.type,'target':getattr(getattr(m,'object',None),'name',None)} for m in o.modifiers],
        'vertex_groups':len(o.vertex_groups)}
meshes=[mesh_info(o) for o in bpy.data.objects if o.type=='MESH']
rigs=[{'name':o.name,'bones':len(o.data.bones),'deform_bones':sum(b.use_deform for b in o.data.bones),
    'bone_names':[b.name for b in o.data.bones],
    'drivers':len(o.animation_data.drivers) if o.animation_data else 0,
    'constraints':sum(len(p.constraints) for p in o.pose.bones)} for o in bpy.data.objects if o.type=='ARMATURE']
images=[{'name':i.name,'packed':bool(i.packed_file),'size':list(i.size),
         'path':i.filepath,'missing':bool(i.filepath and not i.packed_file and not os.path.isfile(bpy.path.abspath(i.filepath)))} for i in bpy.data.images]
data={'status':'completed','blender_version':bpy.app.version_string,'source_path':source,
    'mesh_count':len(meshes),'vertex_count':sum(x['vertices'] for x in meshes),
    'meshes':meshes,'rigs':rigs,'images':images,
    'embedded_texts':[t.name for t in bpy.data.texts],
    'autoexec_enabled':bpy.context.preferences.filepaths.use_scripts_auto_execute,
    'source_unchanged':True,'identity_verified':False}
with open(report,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
'''


def review_blender_source(asset: str, project_name: str) -> dict[str, Any]:
    """Inspect a pinned donor on local Blender without executing donor scripts."""
    if not isinstance(asset,str) or asset not in {'spring', 'tiby_female'} or not isinstance(project_name,str) or not PROJECT_RE.fullmatch(project_name):
        return {'status':'rejected','reason':'invalid_fixed_source_review'}
    value=os.environ.get('LOCAL_AGENT_WORKSPACE','').strip()
    blender=find_blender_executable()
    if not value or blender is None or not blender.is_file():
        return {'status':'blocked','reason':'local_workspace_or_blender_missing'}
    workspace=Path(value).expanduser().resolve()
    output=workspace/'SOURCE_ASSET_REVIEWS'/project_name
    if any(is_link_or_junction(p) for p in [output,*output.parents]):
        return {'status':'rejected','reason':'unsafe_source_review_path'}
    if output.exists():return {'status':'blocked','reason':'source_review_output_exists'}
    if asset=='spring':
        source=workspace/'.local_agent/cache/spring-rig-source-v1/spring/spring/spring.blend'
        expected=SPRING_TRANSFER_BLEND_SHA256
        source_url='https://studio.blender.org/characters/spring/v1/'
        license_name='CC-BY-4.0'
    else:
        cache=workspace/'.local_agent/cache/tiby-cc0-v1'
        if any(is_link_or_junction(p) for p in [cache,*cache.parents]):
            return {'status':'rejected','reason':'unsafe_source_cache'}
        cache.mkdir(parents=True,exist_ok=True)
        source=cache/'Tiby_Character_Female/TIBYF.blend'
        expected='00ab9444a450773b779bbe40b5793d3b9397c0e836d4c321dbfae12b7549c541'
        source_url='https://opengameart.org/content/tiby-3d-rigged-model'
        license_name='CC0'
        if not source.is_file():
            from urllib.request import urlopen
            import zipfile
            archive=cache/'tiby-source.zip'
            try:
                with urlopen('https://opengameart.org/sites/default/files/Tiby_Character_MnF_0.zip',timeout=60) as response:
                    payload=response.read(8_000_001)
                if len(payload)>8_000_000 or hashlib.sha256(payload).hexdigest()!='2c438d05446eedff5e59c879d93922c38fe0e42692e646be783eef278a2a744c':
                    return {'status':'blocked','reason':'tiby_archive_digest_mismatch'}
                if is_link_or_junction(archive):return {'status':'rejected','reason':'unsafe_source_archive'}
                archive.write_bytes(payload)
                with zipfile.ZipFile(archive) as z:
                    members=[i for i in z.infolist() if i.filename.startswith('Tiby_Character_Female/') and i.filename.endswith(('.blend','.png'))]
                    for member in members:
                        target=cache/member.filename
                        if '..' in Path(member.filename).parts or member.filename.startswith('/') or member.file_size>20_000_000 or (member.external_attr>>16)&0o170000==0o120000:
                            raise ValueError('unsafe archive member')
                        if any(is_link_or_junction(p) for p in [target,*target.parents]):raise ValueError('unsafe extraction target')
                        target.parent.mkdir(parents=True,exist_ok=True)
                        with z.open(member) as src,target.open('xb') as dst:
                            dst.write(src.read(20_000_001))
            except (OSError,ValueError,zipfile.BadZipFile) as exc:
                return {'status':'blocked','reason':'tiby_download_or_extract_failed','error_type':type(exc).__name__}
    if any(is_link_or_junction(p) for p in [source,*source.parents]) or not source.is_file():
        return {'status':'blocked','reason':'pinned_source_missing'}
    digest=_spring_sha256(source)
    if digest!=expected:return {'status':'blocked','reason':'source_digest_mismatch'}
    output.mkdir(parents=True,exist_ok=False)
    report=output/'source_inventory.json'
    with tempfile.TemporaryDirectory(prefix='.inspect-',dir=output) as td:
        script=Path(td)/'inspect.py';script.write_text(SOURCE_REVIEW_SCRIPT,encoding='utf-8')
        try:
            proc=subprocess.run([str(blender),'--background','--factory-startup','--disable-autoexec','--offline-mode','--python-exit-code','1','--python',str(script),'--',str(source),str(report)],cwd=output,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300,check=False,shell=False)
        except (OSError,subprocess.TimeoutExpired) as exc:
            return {'status':'failed','reason':'source_inspection_failed','error_type':type(exc).__name__}
    if proc.returncode or not report.is_file():
        return {'status':'failed','reason':'source_inspection_failed','return_code':proc.returncode,'stderr_tail':(proc.stderr or '')[-1800:]}
    data=json.loads(report.read_text('utf-8'))
    unchanged=_spring_sha256(source)==digest
    if not unchanged or data.get('autoexec_enabled') is True:
        return {'status':'failed','reason':'source_changed_or_autoexec_enabled'}
    duplicate_checks=[]
    try:
        from local_agent.studio_server import front_difference
        reviews=workspace/'MIA_REFERENCE_REVIEW'
        fronts=[p/'front.png' for p in reviews.iterdir() if not is_link_or_junction(p) and (p/'front.png').is_file()]
        fronts.sort(key=lambda p:p.stat().st_mtime,reverse=True)
        for first,second in zip(fronts[:6],fronts[1:7]):
            comparison=front_difference(first,second)
            duplicate_checks.append({'first':first.parent.name,'second':second.parent.name,'comparison':comparison})
    except (OSError,ValueError):
        duplicate_checks=[]
    return {'status':'completed','stage':'source_inventory_only','asset':asset,'source_sha256':digest,
        'source_url':source_url,'license':license_name,'source_path':str(source),'report_path':str(report),
        'source_unchanged':unchanged,'identity_verified':False,'recent_review_duplicate_checks':duplicate_checks,
        'mesh_count':data['mesh_count'],'vertex_count':data['vertex_count'],
        'installed_module_sha256':_spring_sha256(Path(__file__)),
        'meshes':sorted(data['meshes'],key=lambda m:(not any(m['materials']),m['name'].startswith(('cs_','BlenRig_')), -m['vertices']))[:45],
        'rigs':[{k:v for k,v in r.items() if k!='bone_names'} for r in data['rigs']],
        'images':data['images'][:25],'embedded_texts':data['embedded_texts'][:20]}


SOURCE_ADAPT_SCRIPT = '"""Editable surface pilot from Spring, independent of stale MeshDeform caches."""\nimport bpy,sys,os,json,math,hashlib,struct\nfrom pathlib import Path\nfrom mathutils import Vector, Quaternion\nargs=sys.argv[sys.argv.index(\'--\')+1:]\nsource,out,accessory_file,reference_path=map(Path,args)\nout.mkdir(parents=True,exist_ok=True)\nbpy.context.preferences.filepaths.use_scripts_auto_execute=False\nbpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False)\n# Build copies from evaluated neutral donor surfaces; do not alter bound cage\n# coordinates or ask old bind caches to infer a new rest shape.\nfor o in bpy.data.objects:\n for m in o.modifiers:\n  if m.type in [\'SUBSURF\',\'PARTICLE_SYSTEM\']:m.show_viewport=False;m.show_render=False\nnames=[\'GEO-spring_head\',\'GEO_spring_arms\',\'GEO-spring_jacket\',\'GEO-spring_pullover\',\'GEO_spring_pants\',\'GEO_spring_boots.l\',\'GEO_spring_boots.r\',\'GEO_spring_eye.l\',\'GEO_spring_eye.r\',\'GEO_spring_eye_cornea.l\',\'GEO_spring_eye_cornea.r\',\'GEO_spring_eyebrows\',\'GEO_spring_eyelashes\',\'GEO_spring_teeth_top\',\'GEO_spring_teeth_bottom\',\'GEO_spring_gums_top\',\'GEO_spring_gums_bottom\',\'GEO_spring_hair_main\',\'GEO_spring_hair_braided\',\'GEO_spring_hair_ears\',\'GEO_spring_hair_ponytail\']\nrig=bpy.data.objects[\'RIG-Spring\'];dg=bpy.context.evaluated_depsgraph_get()\nbone_names=[\'head_def_mstr\',\'neck_1_def\',\'spine_1_def\',\'spine_2_def\',\'spine_3_def\',\'arm_def_L\',\'arm_def_R\',\'forearm_def_L\',\'forearm_def_R\',\'thigh_def_L\',\'thigh_def_R\',\'shin_def_L\',\'shin_def_R\']\nbone_snap={n:[list(rig.matrix_world@rig.pose.bones[n].head),list(rig.matrix_world@rig.pose.bones[n].tail)]for n in bone_names}\nextracted=[]\nfor name in names:\n o=bpy.data.objects.get(name)\n if o is None:raise RuntimeError(\'Missing pinned donor surface \'+name)\n ev=o.evaluated_get(dg);me=bpy.data.meshes.new_from_object(ev,preserve_all_data_layers=True,depsgraph=dg)\n for v in me.vertices:v.co=ev.matrix_world@v.co\n new=bpy.data.objects.new(\'MiaSource_\'+name,me)\n extracted.append((name,new))\n# Derive facial controls by evaluating donor corrective keys, not a new face.\nhead_original=bpy.data.objects[\'GEO-spring_head\'];keydata=head_original.data.shape_keys\nif keydata.animation_data:\n for d in keydata.animation_data.drivers:d.mute=True\nbaseline={k.name:k.value for k in keydata.key_blocks}\nfacial={}\nfor label,values in [(\'blink\',{\'eyelid_up_down_1_L\':1,\'eyelid_up_down_2_L\':1,\'eyelid_up_down_1_R\':1,\'eyelid_up_down_2_R\':1,\'eyelid_low_up_1_L\':.4,\'eyelid_low_up_1_R\':.4}),(\'mouth_open\',{\'maxi_down\':.5})]:\n for k in keydata.key_blocks:k.value=baseline[k.name]\n for n,v in values.items():keydata.key_blocks[n].value=v\n controls=[\'eyelid_up_ctrl_L\',\'eyelid_up_ctrl_R\',\'eyelid_low_ctrl_L\',\'eyelid_low_ctrl_R\'] if label==\'blink\' else [\'mouth_ctrl\']\n saved={n:rig.pose.bones[n].location.copy() for n in controls}\n for n in controls:\n  pb=rig.pose.bones[n];dz=(-.032 if \'up\' in n else .008) if label==\'blink\' else -.028\n  pb.location += pb.bone.matrix_local.to_3x3().inverted() @ Vector((0,0,dz))\n bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();ev=head_original.evaluated_get(dg);me=ev.to_mesh()\n facial[label]=[ev.matrix_world@v.co for v in me.vertices];ev.to_mesh_clear()\n for n,loc in saved.items():rig.pose.bones[n].location=loc\n bpy.context.view_layer.update()\nfor k in keydata.key_blocks:k.value=baseline[k.name]\n# Source archive and .blend remain immutable on disk.\nfor o in list(bpy.data.objects):\n if o not in [n for _,n in extracted]:bpy.data.objects.remove(o,do_unlink=True)\nfor text in list(bpy.data.texts):bpy.data.texts.remove(text)\nscene=bpy.context.scene\nfor name,o in extracted:scene.collection.objects.link(o);o.hide_render=False\nbpy.context.view_layer.update()\ndef mapped(v,name):\n x,y,z=v\n if \'jacket\' in name:\n  hem=max(0,min(1,(.78-z)/.27));waist=math.exp(-((z-.85)/.12)**2)*max(0,1-abs(x)/.22);x*=1+.60*waist;z+=.16*hem;x*=1-.22*hem\n if \'boots\' in name and z>.08:z=.08+(z-.08)*.4\n if \'pants\' in name:x*=1.15\n if z>1.0:\n  h=max(0,min(1,(z-1)/.07));cheek=math.exp(-((z-1.155)/.07)**2)\n  x*=1+h*(.13+.12*cheek)\n  nose=math.exp(-(x/.035)**2-((z-1.155)/.035)**2)*max(0,min(1,(-y-.095)/.045));y+=.019*nose\n  z+=.018*h*math.exp(-((z-1.04)/.055)**2)\n if name==\'GEO_spring_hair_braided\':\n  z-=.055*max(0,min(1,(.16-x)/.32))\n if name==\'GEO_spring_hair_ponytail\':\n  y=.105+(y-.17)*.40;z=1.125+(z-1.125)*.24\n if name==\'GEO_spring_hair_ears\':\n  z=1.14+(z-1.14)*.47\n return Vector((x,y,z))\n# Studio camera remains identical for source/adapted comparisons.\ncamera=bpy.data.objects.new(\'Mia comparison camera\',bpy.data.cameras.new(\'Mia comparison camera\'));scene.collection.objects.link(camera);scene.camera=camera;camera.data.type=\'ORTHO\';camera.data.ortho_scale=1.6\ncamera.location=(0,-4,.74);camera.rotation_euler=(Vector((0,0,.72))-camera.location).to_track_quat(\'-Z\',\'Y\').to_euler()\nfor loc,power,size in [((-2,-3,3),210,3),((2,-1,2),130,2)]:\n l=bpy.data.objects.new(\'Review softbox\',bpy.data.lights.new(\'Review softbox\',\'AREA\'));scene.collection.objects.link(l);l.location=loc;l.data.energy=power;l.data.size=size;l.rotation_euler=(Vector((0,0,.8))-l.location).to_track_quat(\'-Z\',\'Y\').to_euler()\nscene.world=bpy.data.worlds.new(\'Review neutral\');scene.world.use_nodes=True;scene.world.node_tree.nodes[\'Background\'].inputs[0].default_value=(.22,.22,.22,1)\nscene.render.film_transparent=False;scene.render.engine=\'CYCLES\';scene.cycles.samples=24;scene.cycles.use_denoising=True;scene.render.resolution_x=420;scene.render.resolution_y=640;scene.render.resolution_percentage=100;scene.render.image_settings.file_format=\'PNG\';scene.view_settings.view_transform=\'AgX\'\nfor _,o in extracted:\n for p in o.data.polygons:p.use_smooth=True\n m=o.modifiers.new(\'Donor surface smoothing\',\'SUBSURF\');m.levels=1;m.render_levels=1\n# Use simple donor material colors for a geometry-first review.\ndef solid(mat,color,roughness=.6):\n mat.use_nodes=True;n=mat.node_tree.nodes;n.clear();p=n.new(\'ShaderNodeBsdfPrincipled\');p.inputs[\'Base Color\'].default_value=(*color,1);p.inputs[\'Roughness\'].default_value=roughness;out=n.new(\'ShaderNodeOutputMaterial\');mat.node_tree.links.new(p.outputs[\'BSDF\'],out.inputs[\'Surface\'])\nfor m in bpy.data.materials:\n low=m.name.lower()\n if \'hair\' in low:solid(m,(.025,.022,.02))\n elif low==\'mat_spring.eyes_iris\':solid(m,(.25,.35,.08),.35)\n elif low==\'mat_spring.jacket\':solid(m,(.4,.025,.025))\n elif low==\'mat_spring.pants\':solid(m,(.025,.027,.033))\n elif low==\'mat_spring.boots\':solid(m,(.09,.055,.025))\n elif low in [\'mat_spring.head\',\'mat_spring.hands\']:solid(m,(.72,.42,.27),.48)\nscene.render.filepath=str(out/\'before_front.png\');bpy.ops.render.render(write_still=True)\ndef coordhash(mesh):\n h=hashlib.sha256()\n for v in mesh.vertices:h.update(struct.pack(\'<3f\',*v.co))\n return h.hexdigest()\nchanges=[]\nfor name,o in extracted:\n before=coordhash(o.data);original=[v.co.copy() for v in o.data.vertices]\n for v in o.data.vertices:v.co=mapped(v.co,name)\n delta=max(((v.co-a).length for v,a in zip(o.data.vertices,original)),default=0)\n changes.append({\'source_mesh\':name,\'adapted_mesh\':o.name,\'vertex_count\':len(o.data.vertices),\'before_sha256\':before,\'after_sha256\':coordhash(o.data),\'max_displacement\':delta})\n if name==\'GEO-spring_head\':\n  basis=o.shape_key_add(name=\'Basis\');basis.value=0;o.active_shape_key_index=0;o.show_only_shape_key=False\n  for label,coords in facial.items():\n   if len(coords)!=len(o.data.vertices):raise RuntimeError(\'Facial donor topology changed\')\n   key=o.shape_key_add(name=\'Mia_\'+label);key.value=0\n   for p,v in zip(key.data,coords):p.co=mapped(v,name)\n if name in [\'GEO_spring_eye.l\',\'GEO_spring_eye.r\']:\n  iris_ids={i for p in o.data.polygons if p.material_index in [1,2] for i in p.vertices}\n  if iris_ids:\n   cx=sum(o.data.vertices[i].co.x for i in iris_ids)/len(iris_ids);cz=sum(o.data.vertices[i].co.z for i in iris_ids)/len(iris_ids)\n   for i in iris_ids:\n    v=o.data.vertices[i];v.co.x=cx+(v.co.x-cx)*1.32;v.co.z=cz+(v.co.z-cz)*1.32\n for p in o.data.polygons:p.use_smooth=True\nfor m in bpy.data.materials:\n low=m.name.lower()\n if \'hair\' in low:solid(m,(.16,.065,.022))\n elif low==\'mat_spring.eyes_iris\':solid(m,(.16,.06,.017),.35)\n elif low==\'mat_spring.jacket\':solid(m,(.025,.23,.28))\n elif low==\'mat_spring.pullover\':solid(m,(.04,.15,.17))\n elif low==\'mat_spring.pants\':solid(m,(.23,.105,.04))\n elif low==\'mat_spring.boots\':solid(m,(.17,.075,.03))\n elif low==\'omat_hair_viewport\':solid(m,(.16,.065,.022))\n# Fill exposed donor scalp faces after relaxing the braid; avoids skin gaps\n# between the retained crown and swept fringe surfaces.\nhead_mesh=bpy.data.objects[\'MiaSource_GEO-spring_head\'].data\nhair_mat=bpy.data.materials[\'OMAT_Hair_viewport\'];head_mesh.materials.append(hair_mat);hair_index=len(head_mesh.materials)-1\nfor poly in head_mesh.polygons:\n center=sum((head_mesh.vertices[i].co for i in poly.vertices),Vector())/len(poly.vertices)\n if center.z>1.305 or (center.z>1.26 and center.y>.02):poly.material_index=hair_index\n\n# Bones copied from the donor\'s evaluated neutral skeleton, mapped to target\n# space. Separate lightweight pilot rig; full BlenRig stays in original asset.\narm=bpy.data.objects.new(\'Mia_Source_Pilot_Rig\',bpy.data.armatures.new(\'Mia_Source_Pilot_Rig\'));scene.collection.objects.link(arm)\nfor obj in scene.objects:obj.select_set(False)\narm.select_set(True);bpy.context.view_layer.objects.active=arm\nbpy.ops.object.mode_set(mode=\'EDIT\');made={}\nfor n,(h,t) in bone_snap.items():\n b=arm.data.edit_bones.new(n);b.head=mapped(Vector(h),\'rig\');b.tail=mapped(Vector(t),\'rig\');made[n]=b\nparents={\'head_def_mstr\':\'neck_1_def\',\'neck_1_def\':\'spine_3_def\',\'spine_3_def\':\'spine_2_def\',\'spine_2_def\':\'spine_1_def\'}\nfor side in [\'L\',\'R\']:\n parents.update({\'arm_def_\'+side:\'spine_3_def\',\'forearm_def_\'+side:\'arm_def_\'+side,\'thigh_def_\'+side:\'spine_1_def\',\'shin_def_\'+side:\'thigh_def_\'+side})\nfor child,parent in parents.items():made[child].parent=made[parent]\nbpy.ops.object.mode_set(mode=\'OBJECT\')\n# Bounded per-part pilot binding. Requires joint/face visual QA before release.\nfor name,o in extracted:\n if any(k in name for k in [\'head\',\'hair\',\'eye\',\'teeth\',\'gums\']):targets=[\'head_def_mstr\']\n elif \'pants\' in name or \'boots\' in name:targets=[\'thigh_def_L\',\'thigh_def_R\',\'shin_def_L\',\'shin_def_R\']\n elif \'arms\' in name:targets=[\'arm_def_L\',\'arm_def_R\',\'forearm_def_L\',\'forearm_def_R\']\n else:targets=[\'spine_1_def\',\'spine_2_def\',\'spine_3_def\',\'arm_def_L\',\'arm_def_R\',\'forearm_def_L\',\'forearm_def_R\']\n def distance(p,b):\n  a=b.head_local;d=b.tail_local-a;t=max(0,min(1,(p-a).dot(d)/max(d.length_squared,1e-12)));return (p-a-t*d).length\n buckets={}\n for v in o.data.vertices:\n  weights=sorted([(distance(v.co,arm.data.bones[n]),n)for n in targets])[:2]\n  raw=[(n,1/max(d,.008)**2)for d,n in weights];total=sum(w for n,w in raw)\n  for n,w in raw:buckets.setdefault((n,round(w/total,2)),[]).append(v.index)\n for (n,w),ids in buckets.items():\n  vg=o.vertex_groups.get(n) or o.vertex_groups.new(name=n);vg.add(ids,w,\'REPLACE\')\n mod=o.modifiers.new(\'Mapped donor pilot bones\',\'ARMATURE\');mod.object=arm;o.modifiers.move(len(o.modifiers)-1,0)\nfor x in changes:x[\'after_sha256\']=coordhash(bpy.data.objects[x[\'adapted_mesh\']].data)\nfor name in [\'MiaSource_GEO_spring_hair_braided\']:\n obj=bpy.data.objects[name];smooth=obj.modifiers.new(\'Relax donor braid into fringe\',\'SMOOTH\');smooth.factor=.8;smooth.iterations=8;obj.modifiers.move(len(obj.modifiers)-1,0)\n# Reuse accessories from the existing Mia asset after source-first search.\n# accessory_file is fixed by the validated local wrapper\naccessory_names=[]\nif accessory_file.is_file():\n with bpy.data.libraries.load(str(accessory_file),link=False) as (src,dst):\n  dst.objects=[n for n in src.objects if any(k in n.lower() for k in [\'backpack\',\'shoulder_strap\',\'strap_\',\'zipper\',\'golden_zip\'])]\n parts=[o for o in dst.objects if o and o.type==\'MESH\']\n main=next((o for o in parts if o.name.startswith(\'Mustard_backpack_main\')),None)\n if main:\n  bounds=[main.matrix_world@v.co for v in main.data.vertices];lo=min(v.z for v in bounds);hi=max(v.z for v in bounds);oldcenter=(lo+hi)*.5;factor=.34/(hi-lo)\n  for o in parts:\n   scene.collection.objects.link(o);o.hide_render=False;ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get());me=bpy.data.meshes.new_from_object(ev,preserve_all_data_layers=True,depsgraph=bpy.context.evaluated_depsgraph_get());mw=ev.matrix_world.copy();o.data=me;o.parent=None;o.matrix_world.identity()\n   is_zip=any(k in o.name.lower() for k in [\'zipper\',\'golden_zip\']) and \'backpack\' not in o.name.lower()\n   for v in me.vertices:\n    q=mw@v.co\n    if is_zip:q=Vector((q.x*.38,-.147 if \'tooth\' in o.name.lower() or \'pull\' in o.name.lower() else -.143,(q.z-oldcenter)*factor+.84))\n    else:q=Vector((q.x*.45,q.y*.44,(q.z-oldcenter)*factor+.82))\n    v.co=q\n   o.modifiers.clear();group=o.vertex_groups.new(name=\'spine_3_def\');group.add(list(range(len(me.vertices))),1,\'REPLACE\');m=o.modifiers.new(\'Accessory spine attachment\',\'ARMATURE\');m.object=arm\n   accessory_names.append(o.name)\n\n# A-pose for review, using the derived body rig rather than mesh rotation.\nfor side,angle in [(\'L\',.55),(\'R\',-.55)]:\n pb=arm.pose.bones[\'arm_def_\'+side];rest=pb.bone.matrix_local.to_quaternion();pb.rotation_mode=\'QUATERNION\';pb.rotation_quaternion=rest.inverted() @ Quaternion((0,1,0),angle) @ rest\nbpy.context.view_layer.update()\n# Save and reopen before final QA; check actual saved coordinate signatures.\nreference=bpy.data.images.load(str(reference_path),check_existing=False);reference.name=\'Mia_APPROVED_REFERENCE\';reference.pack()\nblend=out/\'mia_spring_source_adapted.blend\';bpy.ops.wm.save_as_mainfile(filepath=str(blend))\nbpy.ops.wm.open_mainfile(filepath=str(blend),load_ui=False)\nreopened=all(coordhash(bpy.data.objects[x[\'adapted_mesh\']].data)==x[\'after_sha256\']for x in changes)\nif not reopened:raise RuntimeError(\'Saved geometry hash mismatch\')\nscene=bpy.context.scene;camera=scene.camera\nfor view,location in [(\'front\',(0,-4,.74)),(\'side\',(4,0,.74)),(\'back\',(0,4,.74)),(\'face\',(0,-4,1.22))]:\n camera.location=location;target=(0,0,1.20) if view==\'face\' else (0,0,.72);camera.rotation_euler=(Vector(target)-camera.location).to_track_quat(\'-Z\',\'Y\').to_euler();camera.data.ortho_scale=.50 if view==\'face\' else 1.6\n scene.render.filepath=str(out/(view+\'.png\'));bpy.ops.render.render(write_still=True)\nhead=bpy.data.objects[\'MiaSource_GEO-spring_head\'];tests={}\nfor label in [\'blink\',\'mouth_open\']:\n key=head.data.shape_keys.key_blocks[\'Mia_\'+label];tests[label+\'_max_delta\']=max(((v.co-b.co).length for v,b in zip(key.data,head.data.shape_keys.key_blocks[\'Basis\'].data)),default=0)\n key.value=1;bpy.context.view_layer.update();camera.location=(0,-4,1.22);camera.rotation_euler=(Vector((0,0,1.20))-camera.location).to_track_quat(\'-Z\',\'Y\').to_euler();camera.data.ortho_scale=.50\n scene.render.filepath=str(out/(label+\'.png\'));bpy.ops.render.render(write_still=True);key.value=0\nrig=bpy.data.objects[\'Mia_Source_Pilot_Rig\'];tests[\'body_bone_count\']=len(rig.data.bones)\nfor part,bone in [(\'head\',\'head_def_mstr\'),(\'arm\',\'forearm_def_L\'),(\'leg\',\'shin_def_L\')]:\n obj=head if part==\'head\' else bpy.data.objects[\'MiaSource_GEO_spring_arms\' if part==\'arm\' else \'MiaSource_GEO_spring_pants\']\n def positions():\n  dg=bpy.context.evaluated_depsgraph_get();ev=obj.evaluated_get(dg);me=ev.to_mesh();p=[v.co.copy() for v in me.vertices];ev.to_mesh_clear();return p\n before=positions();pb=rig.pose.bones[bone];saved_basis=pb.matrix_basis.copy();saved_mode=pb.rotation_mode;pb.rotation_mode=\'XYZ\';pb.rotation_euler[0]=.12;bpy.context.view_layer.update();after=positions();tests[part+\'_pose_max_delta\']=max(((a-b).length for a,b in zip(before,after)),default=0);pb.matrix_basis=saved_basis;pb.rotation_mode=saved_mode;bpy.context.view_layer.update()\n\nreport={\'status\':\'completed\',\'stage\':\'source_geometry_pilot_needs_review\',\'source_blend\':str(source),\'blend_path\':str(blend),\'saved_geometry_reopened_verified\':reopened,\'source_mesh_changes\':changes,\'face_tests\':tests,\'reused_accessories\':accessory_names,\'identity_verified\':False,\'production_ready\':False,\'limitations\':[\'Mapped pilot weights require joint visual QA\',\'Full Spring BlenRig and all corrective keys preserved only in original donor\',\'Hair proxy styling and garment details remain incomplete\',\'Accessory alignment and garment design require visual review\']}\n(out/\'adaptation_report.json\').write_text(json.dumps(report,indent=2))\n'


def adapt_spring_source_to_mia(project_name: str) -> dict[str, Any]:
    """Build a source-derived pilot, prove saved geometry, deliver one comparison."""
    if not isinstance(project_name,str) or not PROJECT_RE.fullmatch(project_name):
        return {'status':'rejected','reason':'invalid_project_name'}
    value=os.environ.get('LOCAL_AGENT_WORKSPACE','').strip()
    blender=find_blender_executable()
    if not value or blender is None or not blender.is_file():
        return {'status':'blocked','reason':'local_workspace_or_blender_missing'}
    workspace=Path(value).expanduser().resolve()
    source=workspace/'.local_agent/cache/spring-rig-source-v1/spring/spring/spring.blend'
    accessory=workspace/'MIA_REFERENCE_REVIEW/mia-approved-ref-rebuild-20261013T222400Z/mia_reference_model.blend'
    reference=workspace/'episode1/assets/references/mia_turnaround_approved_20261012.jpeg'
    out=workspace/'SOURCE_ADAPTATIONS'/project_name
    for p in (source,accessory,reference,out):
        if any(is_link_or_junction(k) for k in [p,*p.parents]):
            return {'status':'rejected','reason':'unsafe_source_adaptation_path'}
    if out.exists():return {'status':'blocked','reason':'unique_source_adaptation_output_exists'}
    if not all(p.is_file() for p in (source,accessory,reference)):
        return {'status':'blocked','reason':'required_donor_accessory_or_approved_reference_missing'}
    digest=_spring_sha256(source);reference_digest=_spring_sha256(reference)
    if digest!=SPRING_TRANSFER_BLEND_SHA256 or reference_digest!='7a3194accfecdb4873bc7d4cd8015edb5a94075ca05c72013c5ad97b4a32e383':
        return {'status':'blocked','reason':'pinned_donor_or_reference_digest_mismatch'}
    accessory_digest=_spring_sha256(accessory)
    out.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='.source-adapt-',dir=out) as td:
        script=Path(td)/'adapt.py';script.write_text(SOURCE_ADAPT_SCRIPT,encoding='utf-8')
        try:
            proc=subprocess.run([str(blender),'--background','--factory-startup','--disable-autoexec','--offline-mode','--python-exit-code','1','--python',str(script),'--',str(source),str(out),str(accessory),str(reference)],cwd=out,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1200,check=False,shell=False)
        except (OSError,subprocess.TimeoutExpired) as exc:
            return {'status':'failed','reason':'source_adaptation_process_failed','error_type':type(exc).__name__}
    (out/'blender_stdout.log').write_text((proc.stdout or '')[-250000:],encoding='utf-8')
    report=out/'adaptation_report.json'
    if proc.returncode or not report.is_file():
        return {'status':'failed','reason':'source_adaptation_failed','return_code':proc.returncode,'stderr_tail':(proc.stderr or '')[-1800:]}
    data=json.loads(report.read_text('utf-8'))
    unchanged=_spring_sha256(source)==digest and _spring_sha256(accessory)==accessory_digest and _spring_sha256(reference)==reference_digest
    changed=sum(m['before_sha256']!=m['after_sha256'] for m in data.get('source_mesh_changes',[]))
    tests=data.get('face_tests',{})
    checks=('blink_max_delta','mouth_open_max_delta','head_pose_max_delta','arm_pose_max_delta','leg_pose_max_delta')
    if not unchanged or not data.get('saved_geometry_reopened_verified') or changed<10 or any(tests.get(k,0)<=.002 for k in checks):
        return {'status':'failed','reason':'source_adaptation_qa_failed','changed_meshes':changed,'tests':tests,'source_unchanged':unchanged}
    import shutil,base64
    ffmpeg=shutil.which('ffmpeg');comparison=out/'comparison.png'
    if ffmpeg:
        result=subprocess.run([ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-i',str(out/'before_front.png'),'-i',str(out/'front.png'),'-filter_complex','hstack=inputs=2','-frames:v','1',str(comparison)],capture_output=True,timeout=60,check=False,shell=False)
        if result.returncode:comparison=None
    else:comparison=None
    thumbs={}
    if ffmpeg:
        for name in ('front','face','side','back','blink','mouth_open'):
            thumb=out/(name+'_thumb.jpg')
            result=subprocess.run([ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-i',str(out/(name+'.png')),'-vf','scale=240:-1','-frames:v','1','-q:v','4',str(thumb)],capture_output=True,timeout=30,check=False,shell=False)
            if not result.returncode and thumb.is_file() and thumb.stat().st_size<35000:
                thumbs[name]=base64.b64encode(thumb.read_bytes()).decode('ascii')
    # Compare original approved pixels and current model through the established
    # Astra endpoint. Provider output is critique only and is never executed.
    astra={'status':'not_requested'}
    try:
        from local_agent.octava_credentials import read_key
        import requests
        key,_=read_key()
        if key:
            content=[{'type':'text','text':'Compare this EXACT approved 4-year-old Mia turnaround (first image) with this source-derived Spring Blender pilot (following images). Identify concrete differences in facial proportions, eyes, hairline, hairstyle, jacket, trousers, boots and backpack. This is NOT production ready. Return a concise English JSON object with likeness_approved=false, differences and prioritized_supported_geometry_changes. Do not give code or URLs. No invented precision percentages.'}]
            for p,mime in [(reference,'image/jpeg'),(out/'face_thumb.jpg','image/jpeg'),(out/'front_thumb.jpg','image/jpeg'),(out/'side_thumb.jpg','image/jpeg')]:
                content.append({'type':'image_url','image_url':{'url':'data:'+mime+';base64,'+base64.b64encode(p.read_bytes()).decode('ascii'),'detail':'high'}})
            response=requests.post('https://octavapi.shop/v1/chat/completions',headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json={'model':'gpt-6-astra','messages':[{'role':'user','content':content}],'max_tokens':1600,'temperature':.2},timeout=(10,150),allow_redirects=False)
            if response.status_code==200:
                answer=response.json()['choices'][0]['message']['content']
                if isinstance(answer,str):
                    (out/'astra_source_critique.txt').write_text(answer[:12000],encoding='utf-8')
                    astra={'status':'completed','original_reference_attached':True,'current_render_attached':True,'reference_sha256':reference_digest,'critique':answer[:4500]}
            else:astra={'status':'failed','http_status':response.status_code}
        else:astra={'status':'unavailable','reason':'astra_key_missing'}
    except Exception as exc:
        astra={'status':'failed','error_type':type(exc).__name__}
    delivery={'status':'not_sent'}
    from local_agent.studio_server import find_recent_duplicate
    repeated=find_recent_duplicate(workspace/'SOURCE_ADAPTATIONS',out)
    if repeated:delivery={'status':'suppressed_duplicate','duplicate_of':repeated['matched_review']}
    if not repeated and comparison and comparison.is_file():
        try:
            from local_agent.studio_server import _telegram_credentials,telegram_notifications_enabled
            import requests
            token,chat=_telegram_credentials()
            if token and chat and telegram_notifications_enabled():
                with comparison.open('rb') as f:
                    response=requests.post('https://api.telegram.org/bot'+token+'/sendPhoto',data={'chat_id':chat,'caption':'Spring → адаптация реальной геометрии. Черновик: сходство Мии ещё НЕ принято. Проверены сохранение, повторное открытие, моргание, рот и движения; детали одежды и волосы требуют правок.'},files={'photo':('source_comparison.png',f,'image/png')},timeout=(8,45),allow_redirects=False)
                delivery={'status':'delivered' if response.status_code==200 and response.json().get('ok') is True else 'failed','comparison_sha256':_spring_sha256(comparison)}
        except Exception as exc:delivery={'status':'failed','error_type':type(exc).__name__}
    return {'status':'completed','stage':'source_geometry_pilot_needs_review','goal_status':'mia_likeness_not_accepted','production_ready':False,'identity_verified':False,
        'source_url':'https://studio.blender.org/characters/spring/v1/','license':'CC-BY-4.0','attribution':'Spring Rig (CC-BY) Blender Foundation | studio.blender.org',
        'source_sha256':digest,'reference_sha256':reference_digest,'accessory_source_sha256':accessory_digest,'source_unchanged':unchanged,
        'installed_module_sha256':_spring_sha256(Path(__file__)),'blend_path':data['blend_path'],'report_path':str(report),'changed_mesh_count':changed,'source_mesh_changes':data['source_mesh_changes'],
        'saved_geometry_reopened_verified':True,'face_and_body_tests':tests,'reused_accessories':data.get('reused_accessories',[]),'thumbnail_jpeg_base64':thumbs,
        'astra':astra,'telegram_comparison':delivery,'limitations':data['limitations']}


def recover_source_adaptation_result(project_name: str, source_task_id: str) -> dict[str, Any]:
    """Read a saved source result after mailbox publication failed. Never rerun."""
    if (not isinstance(project_name,str) or not PROJECT_RE.fullmatch(project_name)
            or not isinstance(source_task_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}',source_task_id)):
        return {'status':'rejected','reason':'invalid_source_recovery_identity'}
    value=os.environ.get('LOCAL_AGENT_WORKSPACE','').strip()
    if not value:return {'status':'blocked','reason':'workspace_missing'}
    workspace=Path(value).expanduser().resolve();out=workspace/'SOURCE_ADAPTATIONS'/project_name
    blend=out/'mia_spring_source_adapted.blend';report=out/'adaptation_report.json'
    if any(is_link_or_junction(p) for k in (blend,report) for p in [k,*k.parents]):
        return {'status':'rejected','reason':'unsafe_recovery_path'}
    if not blend.is_file() or not report.is_file():
        return {'status':'blocked','reason':'source_output_not_created','execution_repeated':False}
    base=json.loads(report.read_text('utf-8'))
    result=None;retained_report=None
    folder=Path(__file__).resolve().parents[1]/'.local_agent/reports'
    if folder.is_dir() and not is_link_or_junction(folder):
        candidates=sorted((p for p in folder.glob('*.json') if not is_link_or_junction(p)),key=lambda p:p.stat().st_mtime,reverse=True)[:80]
        for p in candidates:
            if p.stat().st_size>2_000_000:continue
            try:
                data=json.loads(p.read_text('utf-8'));details=data.get('details',{})
                candidate=details.get('result') if isinstance(details,dict) else None
                if (isinstance(candidate,dict) and candidate.get('task_id')==source_task_id
                        and candidate.get('details',{}).get('blend_path')==str(blend)):
                    result=candidate['details'];result['retained_original_result_bytes']=len(json.dumps(candidate,ensure_ascii=False,indent=2).encode('utf-8'));result['mailbox_limit_bytes']=64000;retained_report=str(p);break
            except (OSError,ValueError):continue
    if result is None:
        result={'status':'completed','stage':base.get('stage'),'blend_path':str(blend),
                'source_mesh_changes':base.get('source_mesh_changes',[]),'face_and_body_tests':base.get('face_tests',{}),
                'saved_geometry_reopened_verified':base.get('saved_geometry_reopened_verified',False),
                'astra':{'status':'unknown'},'telegram_comparison':{'status':'unknown'},
                'identity_verified':False,'production_ready':False}
    result.update({'recovered_existing_output':True,'execution_repeated':False,
        'original_task_id':source_task_id,'retained_full_task_report':retained_report,
        'output_blend_sha256':_spring_sha256(blend),'report_path':str(report)})
    # Validate recorded tests and saved bytes before reporting technical success.
    tests=result.get('face_and_body_tests',{})
    if (not result.get('saved_geometry_reopened_verified')
            or any(tests.get(k,0)<=.002 for k in ('blink_max_delta','mouth_open_max_delta','head_pose_max_delta','arm_pose_max_delta','leg_pose_max_delta'))):
        result['status']='failed';result['reason']='retained_source_qa_failed'
    return result


SOURCE_NEUTRAL_SCRIPT = r'''
import bpy,sys,json,hashlib,struct
from pathlib import Path
from mathutils import Vector
source,out=map(Path,sys.argv[sys.argv.index('--')+1:])
bpy.context.preferences.filepaths.use_scripts_auto_execute=False
bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False)
scene=bpy.context.scene
head=bpy.data.objects['MiaSource_GEO-spring_head'];keys=head.data.shape_keys
before={'key_names':[k.name for k in keys.key_blocks],'values':{k.name:k.value for k in keys.key_blocks},'drivers':len(keys.animation_data.drivers) if keys.animation_data else 0}
keys.animation_data_clear()
# Copies in newer Blender builds may retain corrective keys. Only the new,
# explicitly sampled controls belong to this pilot. Preserve the donor in its
# original file and use the verified target vertices as the neutral basis.
for key in list(keys.key_blocks):
 if key.name not in ('Basis','Mia_blink','Mia_mouth_open'):head.shape_key_remove(key)
keys=head.data.shape_keys
for point,vertex in zip(keys.key_blocks['Basis'].data,head.data.vertices):point.co=vertex.co
for key in keys.key_blocks:key.value=0
head.active_shape_key_index=0;head.show_only_shape_key=False
scene.render.use_compositing=False;scene.render.use_sequencer=False;scene.render.film_transparent=False
scene.render.image_settings.file_format='PNG';scene.cycles.samples=24
scene.frame_set(1);bpy.context.view_layer.update()
# Explicitly zero own controls after frame evaluation as well.
for key in keys.key_blocks:key.value=0
bpy.context.view_layer.update()
output=out/'mia_spring_source_adapted.blend';bpy.ops.wm.save_as_mainfile(filepath=str(output))
bpy.ops.wm.open_mainfile(filepath=str(output),load_ui=False)
scene=bpy.context.scene;head=bpy.data.objects['MiaSource_GEO-spring_head'];keys=head.data.shape_keys
neutral={k.name:k.value for k in keys.key_blocks}
if any(abs(value)>1e-8 for value in neutral.values()):raise RuntimeError('Neutral facial state was not saved')
camera=scene.camera
for view,location in [('front',(0,-4,.74)),('side',(4,0,.74)),('back',(0,4,.74)),('face',(0,-4,1.22))]:
 for k in keys.key_blocks:k.value=0
 scene.frame_set(1);bpy.context.view_layer.update()
 camera.location=location;target=(0,0,1.20) if view=='face' else (0,0,.72);camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.ortho_scale=.50 if view=='face' else 1.6
 scene.render.filepath=str(out/(view+'.png'));bpy.ops.render.render(write_still=True)
checks={}
for name in ('Mia_blink','Mia_mouth_open'):
 for key in keys.key_blocks:key.value=0
 key=keys.key_blocks[name];key.value=1;bpy.context.view_layer.update()
 checks[name+'_max_delta']=max(((a.co-b.co).length for a,b in zip(key.data,keys.key_blocks['Basis'].data)),default=0)
 camera.location=(0,-4,1.22);camera.rotation_euler=(Vector((0,0,1.20))-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.ortho_scale=.50
 scene.render.filepath=str(out/(name+'.png'));bpy.ops.render.render(write_still=True)
for key in keys.key_blocks:key.value=0
bpy.context.view_layer.update()
report={'status':'completed','stage':'neutral_render_state_review','source_blend':str(source),'blend_path':str(output),'facial_state_before':before,'saved_neutral_values':neutral,'facial_shape_deltas':checks,'render_compositing_disabled':True,'source_geometry_reused':True,'identity_verified':False,'production_ready':False}
(out/'neutral_state_report.json').write_text(json.dumps(report,indent=2))
'''


def neutralize_saved_source_model(source_project: str, project_name: str) -> dict[str, Any]:
    """Correct facial/render state using the saved pilot, never rebuild a donor."""
    if any(not isinstance(n,str) or not PROJECT_RE.fullmatch(n) for n in (source_project,project_name)) or source_project==project_name:
        return {'status':'rejected','reason':'invalid_neutral_copy_identity'}
    value=os.environ.get('LOCAL_AGENT_WORKSPACE','').strip();blender=find_blender_executable()
    if not value or blender is None:return {'status':'blocked','reason':'workspace_or_blender_missing'}
    ws=Path(value).expanduser().resolve();source=ws/'SOURCE_ADAPTATIONS'/source_project/'mia_spring_source_adapted.blend';out=ws/'SOURCE_ADAPTATIONS'/project_name
    reference=ws/'episode1/assets/references/mia_turnaround_approved_20261012.jpeg'
    for k in (source,out,reference):
        if any(is_link_or_junction(p) for p in [k,*k.parents]):return {'status':'rejected','reason':'unsafe_neutral_copy_path'}
    if not source.is_file() or out.exists():return {'status':'blocked','reason':'source_missing_or_output_exists'}
    digest=_spring_sha256(source);out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='.neutral-',dir=out) as td:
        script=Path(td)/'neutral.py';script.write_text(SOURCE_NEUTRAL_SCRIPT,encoding='utf-8')
        try:
            proc=subprocess.run([str(blender),'--background','--factory-startup','--disable-autoexec','--offline-mode','--python-exit-code','1','--python',str(script),'--',str(source),str(out)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=600,check=False,shell=False)
        except (OSError,subprocess.TimeoutExpired) as exc:return {'status':'failed','reason':'neutral_copy_process_failed','error_type':type(exc).__name__}
    report=out/'neutral_state_report.json'
    if proc.returncode or not report.is_file():return {'status':'failed','reason':'neutral_copy_failed','return_code':proc.returncode,'stderr_tail':(proc.stderr or '')[-1800:]}
    data=json.loads(report.read_text('utf-8'))
    if _spring_sha256(source)!=digest or any(abs(v)>1e-8 for v in data['saved_neutral_values'].values()):return {'status':'failed','reason':'source_changed_or_neutral_values_invalid'}
    import base64,shutil
    ffmpeg=shutil.which('ffmpeg');thumbs={}
    if ffmpeg:
        for name in ('front','face','side'):
            p=out/(name+'_thumb.jpg')
            proc=subprocess.run([ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-i',str(out/(name+'.png')),'-vf','scale=200:-1','-frames:v','1','-q:v','5',str(p)],capture_output=True,timeout=30,check=False,shell=False)
            if not proc.returncode and p.is_file():thumbs[name]=base64.b64encode(p.read_bytes()).decode('ascii')
    astra=_critique_saved_source_variant(reference,out)
    return {'status':'completed','stage':data['stage'],'source_geometry_reused':True,'source_blend_sha256':digest,'source_unchanged':True,'blend_path':data['blend_path'],'report_path':str(report),'facial_state_before':data['facial_state_before'],'saved_neutral_values':data['saved_neutral_values'],'facial_shape_deltas':data['facial_shape_deltas'],'thumbnail_jpeg_base64':thumbs,'astra':astra,'identity_verified':False,'production_ready':False,'telegram_photo_sent':False}


SOURCE_DETAILS_SCRIPT = "import bpy,sys,json,math,hashlib,struct\nfrom pathlib import Path\nfrom mathutils import Vector\nsource,out,accessory,rain=map(Path,sys.argv[sys.argv.index('--')+1:])\nbpy.context.preferences.filepaths.use_scripts_auto_execute=False\nbpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False)\nscene=bpy.context.scene;rig=bpy.data.objects['Mia_Source_Pilot_Rig'];head=bpy.data.objects['MiaSource_GEO-spring_head']\nkeys=head.data.shape_keys\nif keys.animation_data:keys.animation_data_clear()\nfor k in keys.key_blocks:k.value=0\nhead.show_only_shape_key=False;head.active_shape_key_index=0\n# Apply the same cheek refinement to neutral, blink and mouth samples.\nfor key in keys.key_blocks:\n for p in key.data:\n  x,y,z=p.co;cheek=math.exp(-((abs(x)-.13)/.065)**2-((z-1.145)/.060)**2)*max(0,min(1,(-y-.03)/.08))\n  p.co.x*=1+.06*cheek;p.co.y-=.005*cheek\nfor v,p in zip(head.data.vertices,keys.key_blocks['Basis'].data):v.co=p.co\nskin=head.data.color_attributes.new(name='Mia_Rosy_Skin',type='FLOAT_COLOR',domain='POINT')\nfor p,v in zip(skin.data,head.data.vertices):\n x,y,z=v.co;blush=.6*math.exp(-((abs(x)-.13)/.065)**2-((z-1.155)/.045)**2)*max(0,min(1,(-y-.03)/.08));base=(.73,.36,.22);rose=(.70,.19,.14);p.color=tuple(base[i]*(1-blush)+rose[i]*blush for i in range(3))+(1,)\nmat=head.data.materials[0].copy();mat.name='Mia_Rosy_Source_Skin';head.data.materials[0]=mat\nmat.use_nodes=True;bsdf=mat.node_tree.nodes.get('Principled BSDF');col=mat.node_tree.nodes.new('ShaderNodeVertexColor');col.layer_name='Mia_Rosy_Skin';mat.node_tree.links.new(col.outputs['Color'],bsdf.inputs['Base Color'])\n# Less prominent high collar, preserving the retained donor garment surface.\nbody=bpy.data.objects['MiaSource_GEO-spring_pullover']\nfor v in body.data.vertices:\n if v.co.z>.985:v.co.z=.985+(v.co.z-.985)*.30\n# Reuse hood, pockets, cuffs and lace-up boots from the existing Mia asset.\npatterns=['collapsed_hood','pale_hood_lining','hood_fold_edge','hood_drawstring','cargo_side_pocket','cargo_flap','kangaroo_pocket','pocket_slanted','pocket_lower','boot_','sole_tread','rolled_trouser_cuff']\nwith bpy.data.libraries.load(str(accessory),link=False) as (src,dst):dst.objects=[n for n in src.objects if any(p in n.lower() for p in patterns)]\nparts=[o for o in dst.objects if o and o.type=='MESH'];reused=[]\nfor name in ['MiaSource_GEO_spring_boots.l','MiaSource_GEO_spring_boots.r']:bpy.data.objects[name].hide_render=True\nfor o in parts:\n scene.collection.objects.link(o);bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();ev=o.evaluated_get(dg);me=bpy.data.meshes.new_from_object(ev,preserve_all_data_layers=True,depsgraph=dg);mw=ev.matrix_world.copy();o.data=me;o.parent=None;o.matrix_world.identity();label=o.name.lower()\n points=[mw@v.co for v in me.vertices];center=sum(points,Vector())/max(1,len(points))\n if 'boot_' in label or 'sole_tread' in label:\n  for v,p in zip(me.vertices,points):v.co=Vector((p.x*.35,p.y*.34,p.z*.40))\n  bone='shin_def_L' if center.x>=0 else 'shin_def_R'\n elif 'rolled_trouser_cuff' in label:\n  for v,p in zip(me.vertices,points):v.co=Vector((p.x*.35,p.y*.34,.215+(p.z-center.z)*.40))\n  bone='shin_def_L' if center.x>=0 else 'shin_def_R'\n elif 'cargo' in label:\n  for v,p in zip(me.vertices,points):v.co=Vector((p.x*.40+(.022 if p.x>=0 else -.022),p.y*.40,.52+(p.z-center.z)*.40))\n  bone='thigh_def_L' if center.x>=0 else 'thigh_def_R'\n elif 'hood' in label:\n  for v,p in zip(me.vertices,points):v.co=Vector((p.x*.38,p.y*.42,.995+(p.z-center.z)*.35))\n  bone='spine_3_def'\n else:\n  for v,p in zip(me.vertices,points):v.co=Vector((p.x*.40,p.y*.42-.022,.81+(p.z-center.z)*.35))\n  bone='spine_3_def'\n o.modifiers.clear();o.vertex_groups.clear();group=o.vertex_groups.new(name=bone);group.add(list(range(len(me.vertices))),1,'REPLACE');mod=o.modifiers.new('Detail attached to donor pilot bones','ARMATURE');mod.object=rig;o.hide_render=False;reused.append(o.name)\n# Explicit warm zipper material; old projection shaders must not tint hardware black.\nfor o in scene.objects:\n if not any(k in o.name.lower() for k in ['zipper','golden_zip']):continue\n m=bpy.data.materials.new('Mia_Warm_Zipper_'+o.name);m.use_nodes=True;bs=m.node_tree.nodes['Principled BSDF'];bs.inputs['Base Color'].default_value=(.48,.20,.045,1);bs.inputs['Metallic'].default_value=0;bs.inputs['Emission Color'].default_value=(.48,.20,.045,1);bs.inputs['Emission Strength'].default_value=.25;o.data.materials.clear();o.data.materials.append(m)\n# Adopt modern Rain hair topology, keeping all donor scripts disabled/unloaded.\nwith bpy.data.libraries.load(str(rain),link=False) as (src,dst):dst.objects=[n for n in src.objects if n in ['GEO-rain-hair_main','GEO-rain-hair_strand']]\nhair_parts=[o for o in dst.objects if o]\nif len(hair_parts)!=2:raise RuntimeError('Expected modern Rain hair surfaces missing')\nfor name in ['MiaSource_GEO_spring_hair_main','MiaSource_GEO_spring_hair_braided']:bpy.data.objects[name].hide_render=True\nfor o in hair_parts:\n scene.collection.objects.link(o);mw=o.matrix_world.copy();\n if o.data.shape_keys:o.shape_key_clear()\n o.parent=None;o.constraints.clear();o.animation_data_clear();o.matrix_world.identity();o.modifiers.clear();o.vertex_groups.clear()\n for v in o.data.vertices:\n  p=mw@v.co;v.co=Vector((p.x*1.55,p.y*1.15,(p.z-1.52)*1.20+1.22))\n o.name='Mia_Rain_Source_'+o.name;group=o.vertex_groups.new(name='head_def_mstr');group.add(list(range(len(o.data.vertices))),1,'REPLACE');mod=o.modifiers.new('Hair head binding','ARMATURE');mod.object=rig;sub=o.modifiers.new('Donor hair smoothing','SUBSURF');sub.levels=1;sub.render_levels=1\n mat=bpy.data.materials.new('Mia_Rain_Brown_Hair');mat.use_nodes=True;bs=mat.node_tree.nodes['Principled BSDF'];bs.inputs['Base Color'].default_value=(.18,.075,.025,1);bs.inputs['Roughness'].default_value=.56;noise=mat.node_tree.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=110;noise.inputs['Detail'].default_value=2;bump=mat.node_tree.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.001;mat.node_tree.links.new(noise.outputs['Fac'],bump.inputs['Height']);mat.node_tree.links.new(bump.outputs['Normal'],bs.inputs['Normal']);o.data.materials.clear();o.data.materials.append(mat);o.hide_render=False\n for p in o.data.polygons:p.use_smooth=True\nscene.render.use_compositing=False;scene.render.use_sequencer=False;scene.render.film_transparent=False;scene.render.image_settings.file_format='PNG';scene.cycles.samples=24\nfor text in list(bpy.data.texts):bpy.data.texts.remove(text)\nscene.frame_set(1)\nfor key in keys.key_blocks:key.value=0\nbpy.context.view_layer.update();blend=out/'mia_spring_source_adapted.blend';bpy.ops.wm.save_as_mainfile(filepath=str(blend));bpy.ops.wm.open_mainfile(filepath=str(blend),load_ui=False)\nscene=bpy.context.scene;camera=scene.camera;head=bpy.data.objects['MiaSource_GEO-spring_head']\nfor view,loc in [('front',(0,-4,.74)),('side',(4,0,.74)),('back',(0,4,.74)),('face',(0,-4,1.22))]:\n for key in head.data.shape_keys.key_blocks:key.value=0\n bpy.context.view_layer.update();camera.location=loc;target=(0,0,1.20) if view=='face' else (0,0,.72);camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.ortho_scale=.50 if view=='face' else 1.6;scene.render.filepath=str(out/(view+'.png'));bpy.ops.render.render(write_still=True)\nrig=bpy.data.objects['Mia_Source_Pilot_Rig']\ntests={}\nfor name in ('Mia_blink','Mia_mouth_open'):\n key=head.data.shape_keys.key_blocks[name];tests[name+'_max_delta']=max(((a.co-b.co).length for a,b in zip(key.data,head.data.shape_keys.key_blocks['Basis'].data)),default=0)\nfor part,bone in [('head','head_def_mstr'),('arm','forearm_def_L'),('leg','shin_def_L')]:\n obj=head if part=='head' else bpy.data.objects['MiaSource_GEO_spring_arms' if part=='arm' else 'MiaSource_GEO_spring_pants']\n def positions():\n  dg=bpy.context.evaluated_depsgraph_get();ev=obj.evaluated_get(dg);me=ev.to_mesh();p=[v.co.copy() for v in me.vertices];ev.to_mesh_clear();return p\n before=positions();pb=rig.pose.bones[bone];saved=pb.matrix_basis.copy();mode=pb.rotation_mode;pb.rotation_mode='XYZ';pb.rotation_euler[0]=.12;bpy.context.view_layer.update();after=positions();tests[part+'_pose_max_delta']=max(((a-b).length for a,b in zip(before,after)),default=0);pb.matrix_basis=saved;pb.rotation_mode=mode;bpy.context.view_layer.update()\n\nreport={'status':'completed','stage':'source_detail_refinement_needs_review','source_blend':str(source),'blend_path':str(blend),'geometry_reused_from_last_saved_model':True,'reused_details':reused,'face_and_body_tests':tests,'modern_hair_source':'Rain v3.3 archive / rain_v3.2.blend','neutral_values':{k.name:k.value for k in head.data.shape_keys.key_blocks},'identity_verified':False,'production_ready':False}\n(out/'detail_refinement_report.json').write_text(json.dumps(report,indent=2))\n"


def _critique_saved_source_variant(reference: Path, out: Path) -> dict[str, Any]:
    """Send only the pinned original and current neutral variant for critique."""
    import base64
    if not reference.is_file() or _spring_sha256(reference)!='7a3194accfecdb4873bc7d4cd8015edb5a94075ca05c72013c5ad97b4a32e383':
        return {'status':'blocked','reason':'approved_reference_digest_mismatch'}
    astra={'status':'not_requested'}
    try:
        from local_agent.octava_credentials import read_key
        import requests
        key,_=read_key()
        if key:
            content=[{'type':'text','text':'Compare original approved Mia (first image) and this corrected NEUTRAL model (following images). Do not compare the blink or mouth test. Return concise JSON with likeness_approved, actual remaining differences, and actionable changes to face, side-swept hair, jacket, trousers and boots. Never infer animation state from tests not supplied. No code or URLs.'}]
            for p in [reference,out/'face_thumb.jpg',out/'front_thumb.jpg',out/'side_thumb.jpg']:
                content.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(p.read_bytes()).decode('ascii'),'detail':'high'}})
            response=requests.post('https://octavapi.shop/v1/chat/completions',headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json={'model':'gpt-6-astra','messages':[{'role':'user','content':content}],'max_tokens':1400,'temperature':.2},timeout=(10,150),allow_redirects=False)
            if response.status_code==200:
                payload=response.json();answer=payload['choices'][0]['message']['content'];(out/'astra_neutral_critique.txt').write_text(answer[:10000],encoding='utf-8');astra={'status':'completed','model_requested':'gpt-6-astra','model_returned':payload.get('model'),'reference_sha256':_spring_sha256(reference),'original_reference_attached':True,'current_neutral_render_attached':True,'critique':answer[:5000]}
            else:astra={'status':'failed','http_status':response.status_code}
    except Exception as exc:astra={'status':'failed','error_type':type(exc).__name__}
    return astra


def refine_saved_source_details(source_project: str, project_name: str) -> dict[str, Any]:
    """Refine the saved target using licensed modern hair and existing details."""
    if any(not isinstance(n,str) or not PROJECT_RE.fullmatch(n) for n in (source_project,project_name)) or source_project==project_name:
        return {'status':'rejected','reason':'invalid_source_detail_identity'}
    value=os.environ.get('LOCAL_AGENT_WORKSPACE','').strip();blender=find_blender_executable()
    if not value or blender is None:return {'status':'blocked','reason':'workspace_or_blender_missing'}
    ws=Path(value).expanduser().resolve();source=ws/'SOURCE_ADAPTATIONS'/source_project/'mia_spring_source_adapted.blend';out=ws/'SOURCE_ADAPTATIONS'/project_name
    accessory=ws/'MIA_REFERENCE_REVIEW/mia-approved-ref-rebuild-20261013T222400Z/mia_reference_model.blend'
    reference=ws/'episode1/assets/references/mia_turnaround_approved_20261012.jpeg'
    cache=ws/'.local_agent/cache/rain-hair-source-v1';rain=cache/'rain.blend'
    for k in (source,out,accessory,reference,rain):
        if any(is_link_or_junction(p) for p in [k,*k.parents]):return {'status':'rejected','reason':'unsafe_source_detail_path'}
    if not source.is_file() or not accessory.is_file() or out.exists():return {'status':'blocked','reason':'source_missing_or_output_exists'}
    rain_hash='831ab6d837c679040285862b15dc9ee5180b018442a88aeaf92aaa7509b80258'
    if not rain.is_file():
        from urllib.request import urlopen,Request
        import zipfile,io
        try:
            request=Request('https://studio.blender.org/download-source/files/ee/a7/eea73e55dba1cea31c09848df6a794b2-4.zip?download=1',headers={'User-Agent':'OctavaLocalAgent/1.0'})
            with urlopen(request,timeout=90) as r:payload=r.read(80_000_001)
            if len(payload)>80_000_000 or hashlib.sha256(payload).hexdigest()!='80217f163f6392dc829233d63c2cfb5e1376775bc34101ad14f39631fea70d24':return {'status':'blocked','reason':'rain_archive_checksum_failed'}
            with zipfile.ZipFile(io.BytesIO(payload)) as z:
                member=z.getinfo('Rain v3.3/rain_v3.2.blend')
                if member.file_size>120_000_000:return {'status':'blocked','reason':'rain_member_too_large'}
                raw=z.read(member)
            if hashlib.sha256(raw).hexdigest()!=rain_hash:return {'status':'blocked','reason':'rain_blend_checksum_failed'}
            cache.mkdir(parents=True,exist_ok=True);rain.write_bytes(raw)
        except Exception as exc:return {'status':'blocked','reason':'rain_fixed_download_failed','error_type':type(exc).__name__}
    if _spring_sha256(rain)!=rain_hash:return {'status':'blocked','reason':'rain_blend_checksum_failed'}
    source_hash=_spring_sha256(source);accessory_hash=_spring_sha256(accessory);out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='.details-',dir=out) as td:
        script=Path(td)/'details.py';script.write_text(SOURCE_DETAILS_SCRIPT,encoding='utf-8')
        try:
            proc=subprocess.run([str(blender),'--background','--factory-startup','--disable-autoexec','--offline-mode','--python-exit-code','1','--python',str(script),'--',str(source),str(out),str(accessory),str(rain)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=900,check=False,shell=False)
        except (OSError,subprocess.TimeoutExpired) as exc:return {'status':'failed','reason':'source_details_process_failed','error_type':type(exc).__name__}
    report=out/'detail_refinement_report.json';(out/'blender_stdout.log').write_text((proc.stdout or '')[-200000:],encoding='utf-8')
    if proc.returncode or not report.is_file():return {'status':'failed','reason':'source_details_failed','return_code':proc.returncode,'stderr_tail':(proc.stderr or '')[-1800:]}
    data=json.loads(report.read_text('utf-8'))
    if (_spring_sha256(source)!=source_hash or _spring_sha256(accessory)!=accessory_hash or any(abs(v)>1e-8 for v in data['neutral_values'].values())):
        return {'status':'failed','reason':'source_changed_or_neutral_state_failed'}
    import base64,shutil
    ffmpeg=shutil.which('ffmpeg');thumbs={}
    if ffmpeg:
        for name in ('front','face','side','back'):
            p=out/(name+'_thumb.jpg');proc=subprocess.run([ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-i',str(out/(name+'.png')),'-vf','scale=200:-1','-frames:v','1','-q:v','5',str(p)],capture_output=True,timeout=30,check=False,shell=False)
            if not proc.returncode and p.is_file():thumbs[name]=base64.b64encode(p.read_bytes()).decode('ascii')
    astra=_critique_saved_source_variant(reference,out)
    comparison=out/'comparison.png';delivery={'status':'not_sent'}
    if ffmpeg:
        original=ws/'SOURCE_ADAPTATIONS/mia-spring-adaptation-v1-20261014/before_front.png'
        proc=subprocess.run([ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-i',str(original),'-i',str(out/'front.png'),'-filter_complex','hstack=inputs=2','-frames:v','1',str(comparison)],capture_output=True,timeout=60,check=False,shell=False)
        if not proc.returncode:
            try:
                from local_agent.studio_server import _telegram_credentials,telegram_notifications_enabled,find_recent_duplicate
                import requests
                repeated=find_recent_duplicate(ws/'SOURCE_ADAPTATIONS',out)
                if repeated:delivery={'status':'suppressed_duplicate','duplicate_of':repeated['matched_review']}
                else:
                    token,chat=_telegram_credentials()
                    if token and chat and telegram_notifications_enabled():
                        with comparison.open('rb') as f:
                            response=requests.post('https://api.telegram.org/bot'+token+'/sendPhoto',data={'chat_id':chat,'caption':'Исходная Spring → новая адаптация Мии. Нейтральные глаза исправлены; добавлены волосы Rain, капюшон, карманы и шнурованные ботинки. Черновик: внешность ещё не утверждена.'},files={'photo':('source_details_comparison.png',f,'image/png')},timeout=(8,45),allow_redirects=False)
                        delivery={'status':'delivered' if response.status_code==200 and response.json().get('ok') is True else 'failed','comparison_sha256':_spring_sha256(comparison)}
            except Exception as exc:delivery={'status':'failed','error_type':type(exc).__name__}
    return {'status':'completed','stage':data['stage'],'geometry_reused_from_last_saved_model':True,'source_blend_sha256':source_hash,'source_unchanged':True,'accessory_source_sha256':accessory_hash,'rain_source_sha256':rain_hash,'rain_license':'CC-BY','rain_attribution':'Rain Rig (CC) Blender Foundation | studio.blender.org','blend_path':data['blend_path'],'output_blend_sha256':_spring_sha256(Path(data['blend_path'])),'report_path':str(report),'reused_details':data['reused_details'],'neutral_values':data['neutral_values'],'face_and_body_tests':data['face_and_body_tests'],'thumbnail_jpeg_base64':thumbs,'astra':astra,'telegram_comparison':delivery,'identity_verified':False,'production_ready':False,'limitations':['Face likeness remains subject to reference comparison and user acceptance','Pilot rig weights and advanced facial controls are not production approved']}


SOURCE_POLISH_SCRIPT = "import bpy,sys,json,math,hashlib,struct\nfrom pathlib import Path\nfrom mathutils import Vector\nsource,out=map(Path,sys.argv[sys.argv.index('--')+1:])\nbpy.context.preferences.filepaths.use_scripts_auto_execute=False\nbpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False)\nhead=bpy.data.objects['MiaSource_GEO-spring_head'];keys=head.data.shape_keys\nfor k in keys.key_blocks:k.value=0\nfor key in keys.key_blocks:\n for p in key.data:\n  x,y,z=p.co;front=max(0,min(1,(-y-.03)/.07));cheek=math.exp(-((abs(x)-.13)/.06)**2-((z-1.145)/.05)**2)*front\n  p.co.x*=1+.025*cheek;p.co.y-=.003*cheek\n  smile=math.exp(-((abs(x)-.05)/.025)**2-((z-1.112)/.022)**2)*front;p.co.z+=.0025*smile\nfor v,p in zip(head.data.vertices,keys.key_blocks['Basis'].data):v.co=p.co\nskin=head.data.color_attributes.get('Mia_Rosy_Skin')\nif skin:\n for p,v in zip(skin.data,head.data.vertices):\n  x,y,z=v.co;w=.68*math.exp(-((abs(x)-.13)/.065)**2-((z-1.155)/.045)**2)*max(0,min(1,(-y-.03)/.08));base=(.74,.32,.19);rose=(.70,.15,.105);p.color=tuple(base[i]*(1-w)+rose[i]*w for i in range(3))+(1,)\nscene=bpy.context.scene\nfor o in scene.objects:\n label=o.name.lower()\n if o.type!='MESH':continue\n if label=='miasource_geo_spring_pants':\n  for v in o.data.vertices:\n   center=.08 if v.co.x>=0 else -.08;factor=1.12 if v.co.z>.28 else .94;v.co.x=center+(v.co.x-center)*factor\n if any(k in label for k in ['boot_','sole_tread']):\n  for v in o.data.vertices:\n   center=.08 if v.co.x>=0 else -.08;v.co.x=center+(v.co.x-center)*1.08;v.co.y*=1.05\n if 'cargo' in label:\n  for v in o.data.vertices:v.co.x+=.006 if v.co.x>=0 else -.006\n if label in ['miasource_geo-spring_jacket','collapsed_hood']:\n  for m in o.data.materials:\n   if m is None or not m.use_nodes:continue\n   bs=m.node_tree.nodes.get('Principled BSDF')\n   if bs:\n    for link in list(bs.inputs['Base Color'].links):m.node_tree.links.remove(link)\n    bs.inputs['Base Color'].default_value=(.02,.16,.205,1);bs.inputs['Roughness'].default_value=.76\n    noise=m.node_tree.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=180;noise.inputs['Detail'].default_value=3;bump=m.node_tree.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.0015;m.node_tree.links.new(noise.outputs['Fac'],bump.inputs['Height']);m.node_tree.links.new(bump.outputs['Normal'],bs.inputs['Normal'])\n if 'boot_upper' in label or 'boot_tongue' in label:\n  for m in o.data.materials:\n   if m is None or not m.use_nodes:continue\n   bs=m.node_tree.nodes.get('Principled BSDF')\n   if bs:\n    for link in list(bs.inputs['Base Color'].links):m.node_tree.links.remove(link)\n    bs.inputs['Base Color'].default_value=(.21,.09,.033,1)\n if 'mia_rain_source' in label:\n  for v in o.data.vertices:\n   if v.co.y<-.03:v.co.z+=.003*math.sin(40*v.co.x+22*v.co.z)\n  for m in o.data.materials:\n   if not m or not m.use_nodes:continue\n   bs=m.node_tree.nodes.get('Principled BSDF')\n   if bs:\n    uv=m.node_tree.nodes.new('ShaderNodeTexCoord');sep=m.node_tree.nodes.new('ShaderNodeSeparateXYZ');freq=m.node_tree.nodes.new('ShaderNodeMath');freq.operation='MULTIPLY';freq.inputs[1].default_value=450;wave=m.node_tree.nodes.new('ShaderNodeMath');wave.operation='SINE';bump=m.node_tree.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.0007;m.node_tree.links.new(uv.outputs['UV'],sep.inputs[0]);m.node_tree.links.new(sep.outputs['Y'],freq.inputs[0]);m.node_tree.links.new(freq.outputs[0],wave.inputs[0]);m.node_tree.links.new(wave.outputs[0],bump.inputs['Height']);m.node_tree.links.new(bump.outputs['Normal'],bs.inputs['Normal'])\nscene.render.use_compositing=False;scene.render.use_sequencer=False;scene.render.image_settings.file_format='PNG';scene.cycles.samples=24\nfor k in keys.key_blocks:k.value=0\nbpy.context.view_layer.update();blend=out/'mia_spring_source_adapted.blend';bpy.ops.wm.save_as_mainfile(filepath=str(blend));bpy.ops.wm.open_mainfile(filepath=str(blend),load_ui=False)\nscene=bpy.context.scene;camera=scene.camera;head=bpy.data.objects['MiaSource_GEO-spring_head']\nfor view,loc in [('front',(0,-4,.74)),('side',(4,0,.74)),('back',(0,4,.74)),('face',(0,-4,1.22))]:\n for key in head.data.shape_keys.key_blocks:key.value=0\n bpy.context.view_layer.update();camera.location=loc;target=(0,0,1.20) if view=='face' else (0,0,.72);camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.ortho_scale=.50 if view=='face' else 1.6;scene.render.filepath=str(out/(view+'.png'));bpy.ops.render.render(write_still=True)\ntests={}\nfor name in ('Mia_blink','Mia_mouth_open'):\n key=head.data.shape_keys.key_blocks[name];tests[name+'_max_delta']=max(((a.co-b.co).length for a,b in zip(key.data,head.data.shape_keys.key_blocks['Basis'].data)),default=0)\nreport={'status':'completed','stage':'source_polish_needs_user_review','source_blend':str(source),'blend_path':str(blend),'continues_last_saved_geometry':True,'neutral_values':{k.name:k.value for k in head.data.shape_keys.key_blocks},'facial_shape_deltas':tests,'identity_verified':False,'production_ready':False,'changes':['warmer rosy cheeks and subtle smile','darker textured teal jacket','roomier cargo fit','darker chunkier lace-up boots','directional hair shading and small wave variation']}\n(out/'polish_report.json').write_text(json.dumps(report,indent=2))\n"


def polish_saved_source_model(source_project: str, project_name: str) -> dict[str, Any]:
    """Apply bounded reference critique to the saved model and deliver a bundle."""
    if any(not isinstance(n,str) or not PROJECT_RE.fullmatch(n) for n in (source_project,project_name)) or source_project==project_name:
        return {'status':'rejected','reason':'invalid_source_polish_identity'}
    value=os.environ.get('LOCAL_AGENT_WORKSPACE','').strip();blender=find_blender_executable()
    if not value or blender is None:return {'status':'blocked','reason':'workspace_or_blender_missing'}
    ws=Path(value).expanduser().resolve();source=ws/'SOURCE_ADAPTATIONS'/source_project/'mia_spring_source_adapted.blend';out=ws/'SOURCE_ADAPTATIONS'/project_name
    reference=ws/'episode1/assets/references/mia_turnaround_approved_20261012.jpeg'
    for k in (source,out,reference):
        if any(is_link_or_junction(p) for p in [k,*k.parents]):return {'status':'rejected','reason':'unsafe_source_polish_path'}
    if not source.is_file() or out.exists():return {'status':'blocked','reason':'source_missing_or_output_exists'}
    source_hash=_spring_sha256(source);out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='.polish-',dir=out) as td:
        script=Path(td)/'polish.py';script.write_text(SOURCE_POLISH_SCRIPT,encoding='utf-8')
        try:
            proc=subprocess.run([str(blender),'--background','--factory-startup','--disable-autoexec','--offline-mode','--python-exit-code','1','--python',str(script),'--',str(source),str(out)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=600,check=False,shell=False)
        except (OSError,subprocess.TimeoutExpired) as exc:return {'status':'failed','reason':'source_polish_process_failed','error_type':type(exc).__name__}
    report=out/'polish_report.json'
    if proc.returncode or not report.is_file():return {'status':'failed','reason':'source_polish_failed','return_code':proc.returncode,'stderr_tail':(proc.stderr or '')[-1800:]}
    data=json.loads(report.read_text('utf-8'));blend=Path(data['blend_path'])
    if _spring_sha256(source)!=source_hash or any(abs(v)>1e-8 for v in data['neutral_values'].values()):return {'status':'failed','reason':'source_changed_or_neutral_state_failed'}
    import base64,shutil,zipfile
    ffmpeg=shutil.which('ffmpeg');thumbs={}
    if ffmpeg:
        for name in ('front','face','side'):
            p=out/(name+'_thumb.jpg');result=subprocess.run([ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-i',str(out/(name+'.png')),'-vf','scale=200:-1','-frames:v','1','-q:v','5',str(p)],capture_output=True,timeout=30,check=False,shell=False)
            if not result.returncode and p.is_file():thumbs[name]=base64.b64encode(p.read_bytes()).decode('ascii')
    astra=_critique_saved_source_variant(reference,out)
    attribution=out/'ATTRIBUTION_AND_STATUS.txt'
    attribution.write_text('UNAPPROVED MIA SOURCE DRAFT — not a production release.\nIdentity requires user visual acceptance. Pilot weights and advanced facial rig are not production approved.\n\nSpring Rig (CC-BY) Blender Foundation | studio.blender.org\nhttps://studio.blender.org/characters/spring/v1/\nRain Rig (CC) Blender Foundation | studio.blender.org\nhttps://studio.blender.org/characters/rain/v3/\nDonor licenses: CC-BY; https://creativecommons.org/licenses/by/4.0/\nMia original approved reference remains private; no rights in that reference are granted by donor attribution.\n',encoding='utf-8')
    bundle=out/'Mia_Source_Draft_20261014.zip'
    with zipfile.ZipFile(bundle,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in [blend,report,attribution,*[out/(v+'.png') for v in ('front','face','side','back')]]:
            if is_link_or_junction(path) or not path.is_file():return {'status':'failed','reason':'unsafe_or_missing_bundle_member'}
            archive.write(path,arcname='Mia_Source_Draft.blend' if path==blend else path.name)
    delivery={'status':'not_sent','archive_sha256':_spring_sha256(bundle),'archive_size_bytes':bundle.stat().st_size}
    if bundle.stat().st_size<=49_000_000:
        try:
            from local_agent.studio_server import _telegram_credentials,telegram_notifications_enabled
            import requests
            token,chat=_telegram_credentials()
            if token and chat and telegram_notifications_enabled():
                with bundle.open('rb') as f:
                    response=requests.post('https://api.telegram.org/bot'+token+'/sendDocument',data={'chat_id':chat,'caption':'Мия: настоящий Windows .blend, 4 ракурса, отчёт и лицензии доноров. Внешность ещё требует вашей приёмки; это не готовая серия.'},files={'document':(bundle.name,f,'application/zip')},timeout=(10,180),allow_redirects=False)
                payload=response.json() if response.status_code==200 else {};document=payload.get('result',{}).get('document',{})
                ok=payload.get('ok') is True and document.get('file_size')==bundle.stat().st_size
                delivery.update({'status':'delivered' if ok else 'failed_or_size_unverified','telegram_message_id':payload.get('result',{}).get('message_id')})
        except Exception as exc:delivery.update({'status':'failed','error_type':type(exc).__name__})
    else:delivery['status']='blocked_archive_exceeds_telegram_limit'
    (out/'document_delivery_receipt.json').write_text(json.dumps(delivery,indent=2),encoding='utf-8')
    return {'status':'completed','stage':data['stage'],'continues_last_saved_geometry':True,'source_blend_sha256':source_hash,'source_unchanged':True,'output_blend_sha256':_spring_sha256(blend),'blend_path':str(blend),'bundle_path':str(bundle),'report_path':str(report),'neutral_values':data['neutral_values'],'facial_shape_deltas':data['facial_shape_deltas'],'changes':data['changes'],'thumbnail_jpeg_base64':thumbs,'astra':astra,'telegram_documents':delivery,'identity_verified':False,'production_ready':False,'goal_status':'awaiting_user_visual_acceptance','limitations':['Mapped pilot weights and advanced facial controls still require production QA','No episode rendering was started']}


SPRING_RIG_VIDEO_SCRIPT = r"""
import bpy, sys, json, math, hashlib
from pathlib import Path
from mathutils import Vector
source, video, report = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.filepaths.use_scripts_auto_execute = False
bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
scene = bpy.context.scene
armatures = [o for o in bpy.data.objects if o.type == "ARMATURE" and len(o.data.bones) >= 100]
if not armatures:
    raise RuntimeError("No substantial armature found in the saved Mia file")
armature = max(armatures, key=lambda o: len(o.data.bones))
bone = armature.pose.bones.get("master_torso")
if bone is None:
    raise RuntimeError("Expected tested Spring control master_torso is missing")
mesh_objects = [o for o in scene.objects if o.type == "MESH" and not o.hide_render and len(o.data.vertices)]
if not mesh_objects:
    raise RuntimeError("No visible Mia meshes found")
camera = scene.camera
if camera is None:
    raise RuntimeError("Rigged Mia scene has no saved review camera")
bone.rotation_mode = "XYZ"
neutral = bone.rotation_euler.copy()
if armature.animation_data:
    armature.animation_data.action = None
else:
    armature.animation_data_create()
armature.animation_data.action = bpy.data.actions.new("Mia_Spring_Rig_Motion_Preview")
for frame, delta in ((1,0.0),(18,0.14),(36,0.0),(54,-0.14),(72,0.0)):
    bone.rotation_euler = neutral
    bone.rotation_euler.y += delta
    bone.keyframe_insert(data_path="rotation_euler", frame=frame, group=bone.name)
# Blender inserts Bézier keyframes by default. Do not access Action.fcurves:
# Blender 5.x stores curves in layered-action channelbags.
scene.frame_start, scene.frame_end, scene.render.fps = 1, 72, 24
scene.render.resolution_x = 480
scene.render.resolution_y = 480
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
scene.render.ffmpeg.video_bitrate = 480
scene.render.ffmpeg.maxrate = 800
scene.render.ffmpeg.gopsize = 24
scene.render.filepath = str(video)
scene.render.use_file_extension = True
if scene.render.engine == "CYCLES":
    scene.cycles.samples = 8
scene.render.image_settings.color_mode = "RGB"
scene.render.film_transparent = False
depsgraph = bpy.context.evaluated_depsgraph_get()
samples = []
for obj in mesh_objects:
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    if mesh and len(mesh.vertices):
        stride = max(1, len(mesh.vertices)//300)
        samples.append((obj, [v.co.copy() for v in mesh.vertices[::stride]]))
    evaluated.to_mesh_clear()
scene.frame_set(1)
bpy.context.view_layer.update()
baseline = []
for obj, coords in samples:
    ev = obj.evaluated_get(depsgraph)
    me = ev.to_mesh()
    stride = max(1, len(me.vertices)//300)
    baseline.append((obj, [v.co.copy() for v in me.vertices[::stride]], stride, len(me.vertices)))
    ev.to_mesh_clear()
scene.frame_set(18)
bpy.context.view_layer.update()
max_displacement = 0.0
for obj, before, stride, total in baseline:
    ev = obj.evaluated_get(depsgraph)
    me = ev.to_mesh()
    now = list(me.vertices[::stride])
    for old, new in zip(before, now):
        max_displacement = max(max_displacement, (old-new.co).length)
    ev.to_mesh_clear()
if max_displacement < 1e-5:
    raise RuntimeError("The test control produced no measurable mesh deformation")
scene.frame_set(1)
bpy.ops.render.render(animation=True)
if not video.is_file() or video.stat().st_size < 4096:
    raise RuntimeError("Blender did not create a usable MP4")
data = {
    "status": "completed",
    "source_blend": str(source),
    "video_path": str(video),
    "armature": armature.name,
    "bone_count": len(armature.data.bones),
    "deform_bone_count": sum(1 for b in armature.data.bones if b.use_deform),
    "visible_mesh_count": len(mesh_objects),
    "animation_control": bone.name,
    "control_rotation_y_radians": 0.14,
    "sampled_mesh_max_displacement": max_displacement,
    "frame_count": scene.frame_end-scene.frame_start+1,
    "fps": scene.render.fps,
    "duration_seconds": (scene.frame_end-scene.frame_start+1)/scene.render.fps,
    "resolution": [scene.render.resolution_x,scene.render.resolution_y],
    "render_engine": scene.render.engine,
    "returned_to_neutral_pose": True
}
report.write_text(json.dumps(data, indent=2), encoding="utf-8")
"""

def preview_mia_spring_rig_video(project_name: str) -> dict[str, Any]:
    """Render a short motion test from the existing rigged Mia file without saving it."""
    if not isinstance(project_name, str) or not SPRING_TRANSFER_PROJECT_RE.fullmatch(project_name):
        return {"status":"rejected","reason":"invalid_project_name"}
    root=os.environ.get("LOCAL_AGENT_WORKSPACE","").strip()
    blender=find_blender_executable()
    if not root or blender is None or not blender.is_file():
        return {"status":"blocked","reason":"local_blender_or_workspace_not_configured"}
    workspace=Path(root).expanduser().resolve()
    project=workspace/"SOURCE_ADAPTATIONS"/project_name
    if any(is_link_or_junction(p) for p in (project,project.parent,project.parent.parent)):
        return {"status":"rejected","reason":"unsafe_project_path"}
    project=project.resolve()
    if not project.is_relative_to(workspace) or project==workspace:
        return {"status":"rejected","reason":"unsafe_project_path"}
    source=project/"mia_spring_source_adapted_spring_rig.blend"
    output_name="mia_rig_video_preview_20261015"
    out=project/output_name
    if out.exists():
        for attempt in range(2,100):
            candidate=project/f"{output_name}_retry_{attempt:02d}"
            if not candidate.exists():
                out=candidate
                break
        else:
            return {"status":"blocked","reason":"preview_output_slots_exhausted"}
    if any(is_link_or_junction(p) for p in (source,out)):
        return {"status":"rejected","reason":"unsafe_project_file"}
    if not source.is_file() or source.stat().st_size==0:
        return {"status":"blocked","reason":"rigged_mia_blend_missing"}
    source_hash=_spring_sha256(source)
    out.mkdir(parents=True)
    video=out/"mia_spring_rig_motion_preview.mp4"
    report=out/"preview_report.json"
    with tempfile.TemporaryDirectory(prefix=".rig-video-",dir=out) as td:
        script=Path(td)/"preview.py"
        script.write_text(SPRING_RIG_VIDEO_SCRIPT,encoding="utf-8")
        try:
            proc=subprocess.run(
                [str(blender),"--background","--factory-startup","--disable-autoexec","--offline-mode",
                 "--python-exit-code","1","--python",str(script),"--",str(source),str(video),str(report)],
                capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=900,check=False,shell=False
            )
        except (OSError,subprocess.TimeoutExpired) as exc:
            return {"status":"failed","reason":"rig_video_process_failed","error_type":type(exc).__name__}
    (out/"blender_log.txt").write_text((proc.stdout or "")[-30000:]+"\\n--- STDERR ---\\n"+(proc.stderr or "")[-10000:],encoding="utf-8")
    if proc.returncode or not report.is_file() or not video.is_file():
        return {"status":"failed","reason":"rig_video_render_failed","return_code":proc.returncode,
                "stderr_tail":(proc.stderr or "")[-1400:]}
    data=json.loads(report.read_text("utf-8"))
    if _spring_sha256(source)!=source_hash or data.get("status")!="completed":
        return {"status":"failed","reason":"source_changed_or_render_report_invalid"}
    data["source_blend_sha256"]=source_hash
    data["source_unchanged"]=True
    data["video_sha256"]=_spring_sha256(video)
    data["video_size_bytes"]=video.stat().st_size
    data["report_path"]=str(report)
    data["source_blend"] = str(source)
    report.write_text(json.dumps(data,indent=2),encoding="utf-8")
    return data
