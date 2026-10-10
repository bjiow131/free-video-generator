"""Preflight audit for Blender facial rigs before dialogue animation.

This check is read-only with respect to the source .blend file. Blender opens it in
background mode and emits a JSON report describing likely mouth controls and rig readiness.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")

_AUDIT_SCRIPT = r'''
import bpy, json, re, sys
args = sys.argv[sys.argv.index("--") + 1:]
cfg = json.load(open(args[0], encoding="utf-8"))
def norm(value):
    return re.sub(r"[^a-z0-9а-яё]", "", value.casefold())
def looks_mouth(value):
    n = norm(value)
    tokens = ("mouth", "jaw", "lip", "viseme", "phoneme", " рот", "челюст", "губ", "артикул")
    return any(norm(t) in n for t in tokens)
def write(data):
    with open(cfg["report"], "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
try:
    bpy.ops.wm.open_mainfile(filepath=cfg["source"], load_ui=False)
    objects = list(bpy.data.objects)
    meshes = [o for o in objects if o.type == "MESH"]
    armatures = [o for o in objects if o.type == "ARMATURE"]
    shape_keys = []
    for obj in meshes:
        if obj.data.shape_keys:
            for key in list(obj.data.shape_keys.key_blocks)[1:]:
                if looks_mouth(key.name):
                    shape_keys.append({"object": obj.name, "control": key.name,
                                       "value": float(key.value), "type": "shape_key"})
    facial_bones = []
    for arm in armatures:
        for bone in arm.data.bones:
            if looks_mouth(bone.name):
                facial_bones.append({"object": arm.name, "control": bone.name, "type": "bone"})
    facial_props = []
    for obj in objects:
        try:
            props = list(obj.keys())
        except Exception:
            props = []
        for prop in props:
            if looks_mouth(str(prop)):
                facial_props.append({"object": obj.name, "control": str(prop), "type": "custom_property"})
    drivers = []
    for datablock in list(bpy.data.objects) + list(bpy.data.shape_keys):
        ad = getattr(datablock, "animation_data", None)
        if not ad:
            continue
        for driver in ad.drivers:
            path = str(driver.data_path)
            if looks_mouth(path) or looks_mouth(getattr(datablock, "name", "")):
                drivers.append({"owner": getattr(datablock, "name", ""), "data_path": path})
    actions = []
    for action in bpy.data.actions:
        if looks_mouth(action.name):
            actions.append(action.name)
    controls = shape_keys + facial_bones + facial_props
    if shape_keys:
        status = "ready"
        summary = "Обнаружены shape keys лица; простую анимацию открытия рта можно подготовить."
    elif facial_bones or facial_props:
        status = "needs_review"
        summary = "Обнаружены возможные лицевые контроллеры, но автоматическое управление пока не подтверждено."
    else:
        status = "blocked"
        summary = "Подходящие лицевые контроллеры не обнаружены."
    fixes = []
    if not armatures:
        fixes.append("Добавить риг (armature), если персонажу нужна скелетная анимация.")
    if not shape_keys:
        fixes.append("Для простой речи создать shape key открытия рта (например mouth_open) или явно настроить лицевую кость/свойство.")
    if shape_keys and not any("open" in norm(c["control"]) or "откр" in norm(c["control"]) for c in shape_keys):
        fixes.append("Проверить найденные shape keys вручную: имя не подтверждает, что ключ действительно открывает рот.")
    write({
        "status": status, "summary": summary,
        "source": cfg["source"], "blender_version": bpy.app.version_string,
        "object_count": len(objects), "mesh_count": len(meshes),
        "armatures": [{"name": a.name, "bone_count": len(a.data.bones)} for a in armatures],
        "mouth_controls": controls, "shape_keys": shape_keys,
        "facial_bones": facial_bones, "facial_custom_properties": facial_props,
        "mouth_related_drivers": drivers, "mouth_related_actions": actions,
        "checks": {
            "mesh_present": bool(meshes), "armature_present": bool(armatures),
            "mouth_shape_key_present": bool(shape_keys),
            "possible_face_control_present": bool(controls),
            "mouth_driver_present": bool(drivers)
        },
        "fixes": fixes,
        "limitations": [
            "Имя контроллера — эвристика, не доказательство правильной работы.",
            "Проверка не изменяет исходную сцену и не проверяет визуально деформацию рта.",
            "Для bone/custom-property контроллеров нужна отдельная карта управления, прежде чем автоматически ставить ключи."
        ]
    })
except Exception as exc:
    write({"status": "failed", "reason": "blender_face_rig_audit_failed",
           "error_type": type(exc).__name__})
    raise
'''


def check_face_rig(project_name: str, blend_file: str | None = None, report_name: str = "face_rig_check_result.json") -> dict[str, Any]:
    """Audit one existing .blend file without overwriting the source."""
    if not isinstance(project_name, str) or not _PROJECT_RE.fullmatch(project_name):
        raise ValueError("Invalid project_name.")
    executable_value = os.environ.get("BLENDER_EXECUTABLE", "").strip()
    workspace_value = os.environ.get("LOCAL_AGENT_WORKSPACE", "").strip()
    if not executable_value or not workspace_value:
        return {"status": "blocked", "reason": "set_BLENDER_EXECUTABLE_and_LOCAL_AGENT_WORKSPACE_locally"}
    executable = Path(executable_value).expanduser().resolve()
    workspace = Path(workspace_value).expanduser().resolve()
    if not executable.is_file():
        return {"status": "blocked", "reason": "blender_executable_not_found"}
    requested_project = workspace / project_name
    if requested_project.is_symlink() or getattr(requested_project, "is_junction", lambda: False)():
        raise ValueError("Project directory must not be a symlink or junction.")
    project = requested_project.resolve()
    if not project.is_relative_to(workspace) or project == workspace:
        raise ValueError("Project path must remain inside workspace.")
    if blend_file is not None:
        name = Path(blend_file).name
        if name != blend_file or not name.lower().endswith(".blend"):
            raise ValueError("blend_file must be a filename ending in .blend.")
        source = project / name
    else:
        preferred = ("mia_blockout.blend", "project.blend", "scene.blend", "mouth_motion.blend")
        candidates = [project / name for name in preferred if (project / name).is_file()]
        if not candidates:
            candidates = [p for p in project.glob("*.blend") if p.is_file() and p.name != "face_rig_check_result.json"]
        if len(candidates) != 1:
            return {"status": "blocked", "reason": "source_blend_missing_or_ambiguous",
                    "candidates": sorted(p.name for p in candidates)[:30]}
        source = candidates[0]
    if (not isinstance(report_name, str) or Path(report_name).name != report_name\n            or not report_name.endswith(".json") or report_name in {"", ".", ".."}):\n        raise ValueError("report_name must be a local JSON filename.")\n    report = project / report_name
    if source.is_symlink() or not source.is_file() or source.stat().st_size == 0:
        return {"status": "blocked", "reason": "source_blend_missing_or_invalid"}
    if report.is_symlink() or getattr(report, "is_junction", lambda: False)():
        raise ValueError("Report path must not be a symlink or junction.")
    if report.exists():
        return {"status": "blocked", "reason": "report_exists_refusing_to_overwrite",
                "report_path": str(report)}
    cfg = {"source": str(source), "report": str(report)}
    try:
        with tempfile.TemporaryDirectory(prefix=".face-rig-check-", dir=project) as temp:
            cfg_path = Path(temp) / "task.json"
            script_path = Path(temp) / "audit.py"
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
            script_path.write_text(_AUDIT_SCRIPT, encoding="utf-8")
            proc = subprocess.run(
                [str(executable), "--disable-autoexec", "--background", "--python", str(script_path), "--", str(cfg_path)],
                cwd=str(project), capture_output=True, text=True, timeout=300, check=False, shell=False,
            )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "face_rig_audit_timeout"}
    except OSError as exc:
        return {"status": "error", "error_type": type(exc).__name__}
    if not report.is_file() or report.is_symlink():
        return {"status": "failed", "reason": "face_rig_report_missing", "return_code": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-1500:]}
    try:
        result = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "failed", "reason": "face_rig_report_invalid"}
    if proc.returncode != 0 and result.get("status") != "failed":
        return {"status": "failed", "reason": "blender_exit_nonzero", "return_code": proc.returncode}
    result["task"] = "blender_face_rig_check"
    result["report_path"] = str(report)
    return result
