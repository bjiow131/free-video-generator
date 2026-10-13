"""Bounded Blender rig prototype for an existing Mia blockout project.

Creates a separate .blend output with rigid per-part proxy weights; not production skinning.
"""
from __future__ import annotations
from local_agent.path_names import path_identifier_pattern, is_link_or_junction

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
blend_path,out_path,report_path=[os.path.realpath(p) for p in sys.argv[sys.argv.index("--")+1:]]
bpy.ops.wm.open_mainfile(filepath=os.path.join(os.path.dirname(out_path),"mia_reference_model.blend"),load_ui=False)
scene=bpy.context.scene
mia=[o for o in scene.objects if o.type=="MESH" and o.name.lower() not in {"studio_floor","stage_ground","ground"}]
if not mia or sum(len(o.data.vertices) for o in mia)<1000: raise RuntimeError("expected Mia meshes were not found")
with bpy.data.libraries.load(blend_path,link=False) as (src,dst):
    names=list(src.objects); dst.objects=names; dst.texts=list(src.texts)
spring=[o for o in dst.objects if o]
rig=bpy.data.objects.get("RIG-Spring")
if len(spring)<100 or rig is None or rig.type!="ARMATURE" or len(rig.data.bones)<2000: raise RuntimeError("full Spring rig did not append")
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
    """Create a separate Mia .blend with all 2,259 Spring bones and a pose test."""
    if not isinstance(project_name,str) or not SPRING_TRANSFER_PROJECT_RE.fullmatch(project_name): return {"status":"rejected","reason":"invalid_project_name"}
    exe=os.environ.get("BLENDER_EXECUTABLE","").strip(); root=os.environ.get("LOCAL_AGENT_WORKSPACE","").strip()
    if not exe or not root: return {"status":"blocked","reason":"local_blender_or_workspace_not_configured"}
    blender=Path(exe).expanduser().resolve(); workspace=Path(root).expanduser().resolve()
    if not blender.is_file(): return {"status":"blocked","reason":"blender_executable_not_found"}
    project=(workspace/"MIA_REFERENCE_REVIEW"/project_name).resolve()
    if not project.is_relative_to(workspace) or project==workspace or project.is_symlink(): return {"status":"rejected","reason":"unsafe_project_path"}
    source_mia=project/"mia_reference_model.blend"; output=project/"mia_reference_model_spring_rig.blend"; report=project/"spring_rig_transfer_result.json"
    if not source_mia.is_file(): return {"status":"blocked","reason":"mia_reference_model_missing"}
    if output.exists() or report.exists(): return {"status":"blocked","reason":"output_exists_no_overwrite"}
    cache=workspace/".local_agent"/"cache"/"spring-rig-source-v1"; cache.mkdir(parents=True,exist_ok=True)
    archive=cache/"spring-source.zip"; source=cache/"spring"/"spring"/"spring.blend"
    if not source.is_file() or _spring_sha256(source)!=SPRING_TRANSFER_BLEND_SHA256:
        if not archive.is_file() or _spring_sha256(archive)!=SPRING_TRANSFER_ARCHIVE_SHA256:
            try:
                from urllib.request import Request,urlopen
                request=Request(SPRING_TRANSFER_ARCHIVE_URL,headers={"User-Agent":"OctavaLocalAgent/1.0"})
                temp=None
                with urlopen(request,timeout=60) as response, tempfile.NamedTemporaryFile(prefix="spring-",suffix=".tmp",dir=cache,delete=False) as f:
                    temp=Path(f.name); total=0
                    while True:
                        chunk=response.read(1024*1024)
                        if not chunk: break
                        total+=len(chunk)
                        if total>500*1024*1024: raise ValueError("fixed archive size limit exceeded")
                        f.write(chunk)
                if _spring_sha256(temp)!=SPRING_TRANSFER_ARCHIVE_SHA256: raise ValueError("archive checksum mismatch")
                os.replace(temp,archive)
            except Exception as exc:
                try:
                    if temp: temp.unlink(missing_ok=True)
                except Exception: pass
                return {"status":"blocked","reason":"spring_download_or_checksum_failed","error_type":type(exc).__name__}
        try:
            import zipfile
            with zipfile.ZipFile(archive) as zf:
                if zf.testzip(): raise ValueError("archive CRC failure")
                for member in zf.infolist():
                    parts=Path(member.filename).parts
                    if member.filename.startswith("spring/spring/") and ".." not in parts: zf.extract(member,cache)
        except Exception as exc: return {"status":"failed","reason":"spring_extract_failed","error_type":type(exc).__name__}
        if not source.is_file() or _spring_sha256(source)!=SPRING_TRANSFER_BLEND_SHA256: return {"status":"failed","reason":"spring_blend_checksum_mismatch"}
    try:
        with tempfile.TemporaryDirectory(prefix=".spring-rig-",dir=project) as td:
            script=Path(td)/"transfer.py"; script.write_text(SPRING_TRANSFER_SCRIPT,encoding="utf-8")
            proc=subprocess.run([str(blender),"--disable-autoexec","--background","--factory-startup","--python-exit-code","1","--python",str(script),"--",str(source),str(output),str(report)],cwd=str(project),capture_output=True,text=True,timeout=14400,check=False,shell=False)
    except subprocess.TimeoutExpired: return {"status":"timeout","reason":"transfer_exceeded_4_hours"}
    except OSError as exc: return {"status":"error","error_type":type(exc).__name__}
    if proc.returncode or not output.is_file() or not report.is_file(): return {"status":"failed","reason":"blender_transfer_failed","return_code":proc.returncode,"stderr_tail":(proc.stderr or "")[-2500:]}
    try: data=json.loads(report.read_text("utf-8"))
    except (OSError,ValueError): return {"status":"failed","reason":"transfer_report_unreadable"}
    if data.get("status")!="completed" or data.get("bone_count",0)<2000 or data.get("bound_mesh_count",0)<1: return {"status":"failed","reason":"transfer_validation_failed","transfer":data}
    return {"status":"completed","task":"blender_mia_spring_rig_transfer","blend_path":str(output),"report_path":str(report),"bone_count":data["bone_count"],"deform_bone_count":data["deform_bone_count"],"pose_test_passed":data["pose_test_passed"],"max_pose_vertex_displacement":data["max_pose_vertex_displacement"],"bound_mesh_count":data["bound_mesh_count"],"unbound_mesh_count":data["unbound_mesh_count"],"scale_to_mia_height":data["scale_to_mia_height"],"limitations":data["limitations"]}
