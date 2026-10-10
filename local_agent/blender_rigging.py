"""Bounded Blender skeleton prototype for an existing Mia blockout project.

Creates a separate .blend output. This is a skeleton smoke test only: meshes are
not yet weighted to the armature and therefore are not expected to deform.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any


PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")

_RIG_SCRIPT = r'''
import bpy, json, os, sys
args = sys.argv[sys.argv.index("--") + 1:]
source_path, output_path, report_path = [os.path.realpath(x) for x in args]
bpy.ops.wm.open_mainfile(filepath=source_path, load_ui=False)
arm_data = bpy.data.armatures.new("Mia_Rig")
arm = bpy.data.objects.new("Mia_Rig", arm_data)
bpy.context.scene.collection.objects.link(arm)
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
    if any(word in label for word in ("head", "hair", "eye", "iris", "nose")):
        bone_name = "head"
    elif "neck" in label:
        bone_name = "neck"
    elif "torso" in label:
        bone_name = "spine"
    elif "skirt" in label:
        bone_name = "pelvis"
    elif "upper arm" in label:
        bone_name = "upper_arm" + side
    elif "forearm" in label or "hand" in label:
        bone_name = "forearm" + side
    elif "lower leg" in label or "shoe" in label:
        bone_name = "shin" + side
    elif "leg" in label:
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
    executable = os.environ.get("BLENDER_EXECUTABLE", "").strip()
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not executable or not workspace_value:
        return {"status": "blocked", "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally"}
    blender = Path(executable).expanduser().resolve()
    workspace = Path(workspace_value).expanduser().resolve()
    if not blender.is_file():
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    project = (workspace / project_name).resolve()
    if not project.is_relative_to(workspace) or project == workspace:
        return {"status": "rejected", "reason": "project_outside_workspace"}
    if project.is_symlink() or getattr(project, "is_junction", lambda: False)():
        return {"status": "rejected", "reason": "project_must_not_be_symlink_or_junction"}
    source = project / "mia_blockout.blend"
    output = project / "mia_skeleton.blend"
    report = project / "mia_skeleton_result.json"
    for path in (source, output, report):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            return {"status": "rejected", "reason": "output_path_must_not_be_symlink_or_junction"}
    if not source.is_file() or source.stat().st_size == 0:
        return {"status": "blocked", "reason": "mia_blockout_project_not_found"}
    if output.exists() or report.exists():
        return {"status": "blocked", "reason": "skeleton_outputs_exist_no_overwrite"}
    try:
        with tempfile.TemporaryDirectory(prefix=".mia-rig-", dir=project) as temp:
            script = Path(temp) / "skeleton.py"
            script.write_text(_RIG_SCRIPT, encoding="utf-8")
            proc = subprocess.run(
                [str(blender), "--disable-autoexec", "--background", "--factory-startup",
                 "--python", str(script), "--", str(source), str(output), str(report)],
                cwd=str(project), capture_output=True, text=True, timeout=300,
                check=False, shell=False,
            )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "skeleton_smoke_test_timeout"}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}
    if proc.returncode != 0 or not output.is_file() or output.stat().st_size == 0 or not report.is_file():
        return {"status": "failed", "reason": "blender_skeleton_step_failed",
                "return_code": proc.returncode, "stderr_tail": (proc.stderr or "")[-2000:]}
    try:
        result = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "failed", "reason": "skeleton_report_unreadable"}
    if result.get("status") != "completed" or result.get("stage") != "rigged_proxy_smoke_test" or result.get("bone_count") != 13 or result.get("pose_smoke_test") != "passed_and_reset" or result.get("bound_object_count", 0) < 1:
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
