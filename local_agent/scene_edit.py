"""Safe, allowlisted edits to an existing .blend project."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Any

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,79}$")
_MAX_PROMPT = 1200


class SceneEditError(ValueError):
    """An existing-project edit could not be safely interpreted or executed."""


def _parse(prompt: str) -> dict[str, Any]:
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > _MAX_PROMPT:
        raise SceneEditError(f"Задание должно содержать от 1 до {_MAX_PROMPT} символов.")
    text = prompt.casefold()
    # Replacement of a uniquely named object. The target term must be explicit.
    replace = re.search(r"(?:замени(?:ть)?|поменяй|заменить|исправь|исправить).*?\b(дерево|деревья|куб|сфера|шар|цилиндр|конус|объект|tree|cube|sphere)\b.*?\b(?:на|вместо)\b.*?\b(стол|куб|сферу|шар|цилиндр|конус|дерево|table|cube|sphere)\b", text)
    if replace:
        target = replace.group(1)
        replacement = replace.group(2)
        if target == "деревья":
            raise SceneEditError("Групповая замена деревьев пока не поддерживается: укажите один уникальный объект.")
        mapping = {"стол": "table", "table": "table", "куб": "cube", "cube": "cube",
                   "сферу": "sphere", "шар": "sphere", "sphere": "sphere",
                   "цилиндр": "cylinder", "конус": "cone", "дерево": "tree", "tree": "tree"}
        return {"action": "replace", "target": target, "replacement": mapping[replacement]}
    add = re.search(r"\b(?:добавь|добавить|создай|создать|поставь|поставить)\b.*?\b(стол|куб|сферу|шар|цилиндр|конус|солнце|table|cube|sphere)\b", text)
    if add:
        mapping = {"стол": "table", "table": "table", "куб": "cube", "cube": "cube",
                   "сферу": "sphere", "шар": "sphere", "sphere": "sphere",
                   "цилиндр": "cylinder", "конус": "cone", "солнце": "sphere"}
        return {"action": "add", "replacement": mapping[add.group(1)]}
    delete = re.search(r"(?:удали(?:ть)?|убери|убрать)\s+(?:объект\s+)?[«\"']?([a-zа-яё0-9_. -]{2,60}?)[»\"']?\s*$", text)
    if delete:
        target = delete.group(1).strip(" .,!?:;")
        if target and len(target) <= 60:
            return {"action": "delete", "target": target}
    raise SceneEditError(
        "Эта операция пока не поддерживается безопасным исполнителем. Сейчас доступны: "
        "«добавь куб/сферу/стол», «замени дерево на стол» (если объект уникален), "
        "«удали объект <точное имя>». Остальные задания не изменяют проект."
    )


_SCRIPT = r'''
import bpy, json, os, sys, math, traceback
from mathutils import Vector
args=sys.argv[sys.argv.index("--")+1:]
with open(args[0],"r",encoding="utf-8") as f: cfg=json.load(f)
def _agent_excepthook(exc_type, exc, tb):
    try:
        with open(cfg["result"],"w",encoding="utf-8") as stream:
            json.dump({"status":"failed","error":str(exc),"error_type":getattr(exc_type,"__name__","Exception")},stream,ensure_ascii=False)
    except Exception:
        pass
    traceback.print_exception(exc_type,exc,tb)
sys.excepthook=_agent_excepthook
source=os.path.realpath(cfg["source"])
destination=os.path.realpath(cfg["destination"])
bpy.ops.wm.open_mainfile(filepath=source)
scene=bpy.context.scene
action=cfg["action"]
target=cfg.get("target","").casefold().strip()
replacement=cfg.get("replacement","")
def matches():
    aliases={"дерево":"tree","деревья":"tree","куб":"cube","сфера":"sphere","шар":"sphere"}
    terms={target}
    if target in aliases: terms.add(aliases[target])
    return [o for o in bpy.data.objects if any(term in o.name.casefold() for term in terms)]
def mat(name, color):
    m=bpy.data.materials.new(name); m.diffuse_color=(*color,1)
    m.use_nodes=True
    bsdf=m.node_tree.nodes.get("Principled BSDF")
    if bsdf: bsdf.inputs["Base Color"].default_value=(*color,1)
    return m
def create_table(location, scale=1.0, prefix="Table"):
    wood=mat(prefix+" | wood",(0.42,0.22,0.09))
    bpy.ops.mesh.primitive_cube_add(size=1, location=(location.x,location.y,location.z+0.65*scale))
    top=bpy.context.object; top.name=prefix+" | tabletop"; top.dimensions=(1.8*scale,1.0*scale,0.14*scale); top.data.materials.append(wood)
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    for i,(x,y) in enumerate([(-0.72,-0.34),(0.72,-0.34),(-0.72,0.34),(0.72,0.34)]):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(location.x+x*scale,location.y+y*scale,location.z+0.3*scale))
        leg=bpy.context.object; leg.name=prefix+" | leg %02d"%(i+1); leg.dimensions=(0.12*scale,0.12*scale,0.6*scale); leg.data.materials.append(wood)
        bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
if action=="replace":
    found=matches()
    if len(found)!=1:
        raise RuntimeError("TARGET_MATCH_COUNT:"+str(len(found))+":"+json.dumps([o.name for o in found[:30]],ensure_ascii=False))
    old=found[0]
    loc=old.location.copy(); scale=max(0.1,max(old.dimensions))
    old_name=old.name
    bpy.data.objects.remove(old,do_unlink=True)
    if replacement=="table": create_table(loc,scale,"Replaced "+old_name)
    elif replacement=="cube":
        bpy.ops.mesh.primitive_cube_add(size=1,location=loc); obj=bpy.context.object; obj.name="Replacement cube"; obj.scale=(scale,)*3
    elif replacement=="sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=20,location=loc); obj=bpy.context.object; obj.name="Replacement sphere"; obj.scale=(scale/2,)*3
    elif replacement=="cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=scale/2,depth=scale,location=loc); bpy.context.object.name="Replacement cylinder"
    elif replacement=="cone":
        bpy.ops.mesh.primitive_cone_add(vertices=32,radius1=scale/2,radius2=0,depth=scale,location=loc); bpy.context.object.name="Replacement cone"
    elif replacement=="tree":
        bpy.ops.mesh.primitive_cone_add(vertices=8,radius1=0.8,radius2=0,depth=2,location=(loc.x,loc.y,loc.z+1)); bpy.context.object.name="Replacement stylized tree"
elif action=="add":
    if replacement=="table": create_table(Vector((0,0,0)),1,"Added table")
    elif replacement=="cube":
        bpy.ops.mesh.primitive_cube_add(size=1,location=(0,0,0.5)); bpy.context.object.name="Added cube"
    elif replacement=="sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=20,location=(0,0,0.5)); bpy.context.object.name="Added sphere"
    elif replacement=="cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=0.5,depth=1,location=(0,0,0.5)); bpy.context.object.name="Added cylinder"
    elif replacement=="cone":
        bpy.ops.mesh.primitive_cone_add(vertices=32,radius1=0.5,radius2=0,depth=1,location=(0,0,0.5)); bpy.context.object.name="Added cone"
else:
    found=matches()
    if len(found)!=1:
        raise RuntimeError("TARGET_MATCH_COUNT:"+str(len(found))+":"+json.dumps([o.name for o in found[:30]],ensure_ascii=False))
    bpy.data.objects.remove(found[0],do_unlink=True)
os.makedirs(os.path.dirname(destination),exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=destination)
preview=os.path.splitext(destination)[0]+"_preview.png"
if scene.camera is None:
    bpy.ops.object.camera_add(location=(8,-10,7))
    camera=bpy.context.object
    camera.name="Agent | generated preview camera"
    camera.rotation_euler=(Vector((0,0,0.5))-camera.location).to_track_quat("-Z","Y").to_euler()
    scene.camera=camera
if not any(o.type=="LIGHT" for o in scene.objects):
    bpy.ops.object.light_add(type="AREA", location=(-4,-4,7))
    light=bpy.context.object
    light.name="Agent | generated preview light"
    light.data.energy=1200
    light.data.shape="DISK"
    light.data.size=6
    light.rotation_euler=(Vector((0,0,0.5))-light.location).to_track_quat("-Z","Y").to_euler()
scene.render.filepath=preview
scene.render.image_settings.file_format="PNG"
scene.render.resolution_percentage=min(scene.render.resolution_percentage or 50,50)
try: bpy.ops.render.render(write_still=True)
except Exception as exc:
    raise RuntimeError("PREVIEW_RENDER_FAILED:"+str(exc))
with open(cfg["result"],"w",encoding="utf-8") as f:
    json.dump({"status":"completed","blend_path":destination,"preview_path":preview,"action":action,"object_count":len(bpy.data.objects)},f,ensure_ascii=False)
'''


def edit_existing_scene(prompt: str, source_project: str | Path, blender_executable: str, workspace: str | Path, timeout_seconds: int = 1200) -> dict[str, Any]:
    plan = _parse(prompt)
    source = Path(source_project).expanduser().resolve()
    blender = Path(blender_executable).expanduser().resolve()
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() != ".blend" or not source.is_file():
        raise SceneEditError("Выберите существующий файл .blend.")
    if not blender.is_file():
        raise SceneEditError("Исполняемый файл Blender не найден.")
    if source.is_symlink() or getattr(source, "is_junction", lambda: False)():
        raise SceneEditError("Исходный проект не должен быть символьной ссылкой.")
    staging = root / ("agent_edit_" + time.strftime("%Y%m%d_%H%M%S") + f"_{os.getpid()}")
    staging.mkdir(parents=True, exist_ok=False)
    destination = staging / "edited_scene.blend"
    result_path = staging / "edit_result.json"
    script_path = staging / "edit_scene.py"
    config_path = staging / "edit_config.json"
    script_path.write_text(_SCRIPT, encoding="utf-8")
    config = dict(plan, source=str(source), destination=str(destination), result=str(result_path))
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    stdout_path, stderr_path = staging / "blender_stdout.log", staging / "blender_stderr.log"
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            proc = subprocess.Popen([str(blender), str(source), "--python", str(script_path), "--", str(config_path)],
                                    cwd=str(staging), stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                    shell=False, close_fds=True)
            deadline = time.monotonic() + max(30, min(int(timeout_seconds), 7200))
            while time.monotonic() < deadline:
                if result_path.is_file() and result_path.stat().st_size > 0:
                    try:
                        result = json.loads(result_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        result = {}
                    if result.get("status") == "completed":
                        break
                    if result.get("status") == "failed":
                        raise SceneEditError("Blender отклонил изменение: " + str(result.get("error", "неизвестная ошибка"))[:1800])
                code = proc.poll()
                if code is not None:
                    break
                # A Blender GUI can stay alive after a script error. Detect known
                # task errors from its redirected log rather than waiting 20 minutes.
                try:
                    log_tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-6000:]
                except OSError:
                    log_tail = ""
                if "TARGET_MATCH_COUNT:" in log_tail:
                    details = log_tail.split("TARGET_MATCH_COUNT:", 1)[1].splitlines()[0]
                    raise SceneEditError("Не удалось однозначно определить объект. Уточните его имя. Совпадения: " + details[:1000])
                if "Traceback (most recent call last)" in log_tail or "Error: Python" in log_tail:
                    raise SceneEditError("Blender сообщил об ошибке выполнения сценария. Исходный проект не перезаписан. Последние строки журнала:\\n" + log_tail[-2500:])
                time.sleep(0.25)
            else:
                # The visible Blender GUI can stay open after the operation completed.
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: proc.kill()
                raise SceneEditError("Операция в Blender превысила допустимое время ожидания.")
        if not result_path.is_file():
            tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            if "TARGET_MATCH_COUNT:" in tail:
                details = tail.split("TARGET_MATCH_COUNT:", 1)[1].splitlines()[0]
                raise SceneEditError("Не удалось однозначно определить объект для изменения. Уточните его имя в задании. Найденные совпадения: " + details[:1000])
            raise SceneEditError(f"Blender не создал отчёт об изменении (код {proc.poll()}). {tail}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("status") != "completed" or not destination.is_file() or destination.stat().st_size == 0:
            raise SceneEditError("Blender не подтвердил успешное сохранение изменённой сцены.")
        if not result.get("preview_path") or not Path(result["preview_path"]).is_file():
            raise SceneEditError("Сцена изменена, но предпросмотр PNG не создан.")
        result["source_project"] = str(source)
        result["prompt_summary"] = prompt.strip()
        return result
    except OSError as exc:
        raise SceneEditError(f"Не удалось запустить Blender ({type(exc).__name__}).") from exc
