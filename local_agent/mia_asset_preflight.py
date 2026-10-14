"""Read-only structural passport for one workspace-contained Blender file."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

_SAFE_RELATIVE_BLEND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,511}[.]blend$", re.IGNORECASE)
_SAFE_TASK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")

# Executed by Blender with --disable-autoexec. It opens the requested project,
# inventories useful rigging facts, and never invokes save operators.
_BLENDER_SCRIPT = r'''
import bpy, json, os, sys
args = sys.argv[sys.argv.index("--") + 1:]
source_path = os.path.realpath(args[0])
report_path = os.path.realpath(args[1])
bpy.ops.wm.open_mainfile(filepath=source_path, load_ui=False)
scene = bpy.context.scene

def animation_summary(owner):
    animation = getattr(owner, "animation_data", None)
    if animation is None:
        return None
    action = getattr(animation, "action", None)
    return {
        "action": action.name if action else None,
        "drivers": len(animation.drivers),
        "nla_tracks": len(animation.nla_tracks),
    }

objects = []
for obj in list(bpy.data.objects)[:500]:
    item = {
        "name": obj.name[:200],
        "type": obj.type,
        "parent": obj.parent.name[:200] if obj.parent else None,
        "dimensions": [round(float(v), 6) for v in obj.dimensions],
        "modifiers": [{"name": m.name[:120], "type": m.type,
                       "target": getattr(getattr(m, "object", None), "name", None)}
                      for m in list(obj.modifiers)[:100]],
        "animation": animation_summary(obj),
    }
    if obj.type == "MESH":
        data = obj.data
        item["mesh"] = {
            "vertices": len(data.vertices),
            "edges": len(data.edges),
            "polygons": len(data.polygons),
            "materials": [m.name[:160] if m else None for m in data.materials[:100]],
            "shape_keys": ([key.name[:160] for key in data.shape_keys.key_blocks[:300]]
                           if data.shape_keys else []),
            "shape_key_animation": animation_summary(data.shape_keys) if data.shape_keys else None,
        }
    elif obj.type == "ARMATURE":
        item["armature"] = {
            "bone_count": len(obj.data.bones),
            "bones": [bone.name[:160] for bone in list(obj.data.bones)[:500]],
            "animation": animation_summary(obj.data),
        }
    objects.append(item)

report = {
    "status": "completed",
    "source_blend": source_path,
    "blender_version": bpy.app.version_string,
    "scene": scene.name[:200],
    "object_count": len(bpy.data.objects),
    "object_count_reported": len(objects),
    "objects_truncated": len(bpy.data.objects) > len(objects),
    "mesh_count": sum(1 for o in bpy.data.objects if o.type == "MESH"),
    "armature_count": sum(1 for o in bpy.data.objects if o.type == "ARMATURE"),
    "curve_count": sum(1 for o in bpy.data.objects if o.type in {"CURVE", "CURVES"}),
    "action_count": len(bpy.data.actions),
    "actions": [a.name[:200] for a in list(bpy.data.actions)[:300]],
    "scene_animation": animation_summary(scene),
    "objects": objects,
    "saved_or_modified": False,
}
with open(report_path, "w", encoding="utf-8") as stream:
    json.dump(report, stream, ensure_ascii=False)
'''


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_workspace_asset(workspace: Path, relative_path: str) -> Path:
    if (not isinstance(relative_path, str) or not _SAFE_RELATIVE_BLEND.fullmatch(relative_path)
            or "\\" in relative_path or ":" in relative_path):
        raise ValueError("invalid_workspace_relative_blend_path")
    parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("invalid_workspace_relative_blend_path")
    current = workspace
    for part in parts:
        current = current / part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise ValueError("asset_path_contains_link")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(workspace) or resolved == workspace:
        raise ValueError("asset_path_outside_workspace")
    if not resolved.is_file() or resolved.suffix.lower() != ".blend":
        raise ValueError("asset_is_not_a_regular_blend_file")
    return resolved


def run_mia_asset_preflight(source_blend: str, task_id: str) -> dict[str, Any]:
    """Inventory a workspace-relative .blend without saving or changing it."""
    if not isinstance(task_id, str) or not _SAFE_TASK.fullmatch(task_id):
        return {"status": "rejected", "reason": "invalid_task_id"}

    executable = os.environ.get("BLENDER_EXECUTABLE", "").strip()
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not executable or not workspace_value:
        return {"status": "blocked", "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally"}
    blender = Path(executable).expanduser().resolve()
    workspace = Path(workspace_value).expanduser().resolve()
    if not blender.is_file():
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    try:
        source = _resolve_workspace_asset(workspace, source_blend)
    except (ValueError, OSError, RuntimeError):
        return {"status": "rejected", "reason": "invalid_or_unavailable_workspace_asset"}

    if source.stat().st_size <= 0:
        return {"status": "rejected", "reason": "source_blend_is_empty"}
    source_hash = _sha256(source)

    try:
        with tempfile.TemporaryDirectory(prefix="mia-asset-passport-") as temp_name:
            temp = Path(temp_name)
            script = temp / "passport.py"
            report = temp / "passport.json"
            script.write_text(_BLENDER_SCRIPT, encoding="utf-8")
            proc = subprocess.run(
                [str(blender), "--disable-autoexec", "--background", "--factory-startup",
                 "--python", str(script), "--", str(source), str(report)],
                cwd=str(workspace), capture_output=True, text=True, timeout=300,
                check=False, shell=False,
            )
            if proc.returncode != 0 or not report.is_file() or report.stat().st_size > 2_000_000:
                return {
                    "status": "failed",
                    "reason": "blender_passport_failed",
                    "return_code": proc.returncode,
                    "stderr_tail": (proc.stderr or "")[-2000:],
                }
            data = json.loads(report.read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "blender_passport_timeout"}
    except (OSError, ValueError, json.JSONDecodeError):
        return {"status": "failed", "reason": "blender_passport_report_unreadable"}

    if data.get("status") != "completed" or data.get("saved_or_modified") is not False:
        return {"status": "failed", "reason": "blender_passport_validation_failed"}
    return {
        "status": "completed",
        "task": "blender_mia_asset_preflight",
        "source_blend": source_blend,
        "source_sha256": source_hash,
        "source_size_bytes": source.stat().st_size,
        "passport": data,
        "note": "Read-only structural inventory; visual quality, license, and production readiness require separate review.",
    }
