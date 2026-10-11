"""Local, data-only state for the Blender AI Agent studio.

No executable instructions, external URLs or remote API keys are stored here.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from local_agent.story_plan import validate_story_plan, StoryPlanError

_ID = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{0,47}\Z")
_PROJECT = re.compile(r"[a-zA-Z0-9_-]{1,48}\Z")
_MAX_BYTES = 256_000
_LOCK = threading.RLock()


class StudioError(ValueError):
    pass


class StudioConflict(StudioError):
    pass


def _string(value: Any, label: str, limit: int = 2000) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise StudioError(f"{label}: expected text of up to {limit} characters")
    return value.strip()


def default_state(project: str) -> dict[str, Any]:
    return {
        "schema_version": 1, "revision": 0, "project": project,
        "title": "Мия и её приключения", "task": "", "active_scene": "",
        "characters": [{"id": "mia", "name": "Мия", "role": "Главная героиня",
                        "age": "4 года", "traits": "Любит улиток, самокат и велосипед",
                        "appearance": "Внешность определяется карточкой референса",
                        "outfit": "", "voice": "", "reference": ""}],
        "props": [
            {"id": "snail", "name": "Улитка", "kind": "Персонаж / объект", "description": "Любимая улитка Мии", "reference": ""},
            {"id": "scooter", "name": "Жёлтый самокат", "kind": "Реквизит", "description": "Самокат Мии", "reference": ""},
            {"id": "bicycle", "name": "Велосипед", "kind": "Реквизит", "description": "Велосипед Мии", "reference": ""},
        ],
        "scenes": [],
        "settings": {"duration": 8, "aspect": "9:16", "style": "3D-анимация",
                     "camera": "Плавное слежение", "animation": "Естественное движение",
                     "resolution": "360x640", "fps": 12, "sound": "Отдельное аудио"},
    }


def validate_state(raw: Any, project: str) -> dict[str, Any]:
    """Reject malformed or unbounded data before persisting it."""
    if not isinstance(raw, dict) or set(raw) != set(default_state(project)):
        raise StudioError("Invalid studio state fields")
    if raw.get("schema_version") != 1 or isinstance(raw.get("revision"), bool) or not isinstance(raw.get("revision"), int) or raw["revision"] < 0:
        raise StudioError("Invalid studio state version")
    if raw.get("project") != project:
        raise StudioError("Project mismatch")
    state = {"schema_version": 1, "revision": raw["revision"], "project": project,
             "title": _string(raw.get("title"), "title", 180),
             "task": _string(raw.get("task"), "task", 4000),
             "active_scene": _string(raw.get("active_scene"), "active_scene", 48)}
    if not state["title"]:
        raise StudioError("Project title is required")
    for group, fields, limit in (
        ("characters", {"id": 48, "name": 100, "role": 120, "age": 80, "traits": 900, "appearance": 1200, "outfit": 900, "voice": 200, "reference": 180}, 60),
        ("props", {"id": 48, "name": 120, "kind": 100, "description": 1500, "reference": 180}, 200),
        ("scenes", {"id": 48, "title": 180, "prompt": 3000, "location": 600, "camera": 600, "style": 200, "animation": 200, "status": 60, "preview": 180}, 80),
    ):
        records = raw.get(group)
        if not isinstance(records, list) or len(records) > limit:
            raise StudioError(f"Invalid {group} list")
        cleaned, used = [], set()
        for item in records:
            if not isinstance(item, dict):
                raise StudioError(f"Invalid {group} entry")
            expected = set(fields)
            if group == "scenes":
                expected |= {"duration", "characters", "props"}
            if set(item) != expected:
                raise StudioError(f"Invalid {group} fields")
            record = {key: _string(item.get(key), f"{group}.{key}", cap)
                      for key, cap in fields.items()}
            if not _ID.fullmatch(record["id"]) or record["id"] in used:
                raise StudioError(f"Invalid or duplicate {group} ID")
            used.add(record["id"])
            if not record.get("name", record.get("title")):
                raise StudioError(f"Missing {group} name")
            for image_key in ("reference", "preview"):
                if image_key in record and record[image_key] and not re.fullmatch(r"[a-f0-9]{32}\.(png|jpg|webp)", record[image_key]):
                    raise StudioError("Invalid media identifier")
            if group == "scenes":
                seconds = item.get("duration")
                if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= 120:
                    raise StudioError("Scene duration must be 1-120 seconds")
                for key in ("characters", "props"):
                    ids = item.get(key)
                    if not isinstance(ids, list) or len(ids) > 40 or any(not isinstance(v, str) or not _ID.fullmatch(v) for v in ids) or len(set(ids)) != len(ids):
                        raise StudioError(f"Invalid scene {key}")
                    record[key] = ids[:]
                record["duration"] = seconds
                if record["status"] not in {"черновик", "план готов", "ошибка"}:
                    raise StudioError("Invalid scene status")
            cleaned.append(record)
        state[group] = cleaned
    character_ids = {v["id"] for v in state["characters"]}
    prop_ids = {v["id"] for v in state["props"]}
    scene_ids = {v["id"] for v in state["scenes"]}
    if state["active_scene"] and state["active_scene"] not in scene_ids:
        raise StudioError("Unknown active scene")
    for scene in state["scenes"]:
        if not set(scene["characters"]).issubset(character_ids) or not set(scene["props"]).issubset(prop_ids):
            raise StudioError("Scene references missing assets")
    cfg = raw.get("settings")
    if not isinstance(cfg, dict) or set(cfg) != {"duration", "aspect", "style", "camera", "animation", "resolution", "fps", "sound"}:
        raise StudioError("Invalid settings")
    duration, fps = cfg["duration"], cfg["fps"]
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (duration, fps)) or not 1 <= duration <= 120 or not 1 <= fps <= 60:
        raise StudioError("Invalid duration/fps")
    if cfg["aspect"] not in ("9:16", "16:9", "1:1") or cfg["resolution"] not in ("360x640", "640x360", "512x512", "720x1280", "1280x720"):
        raise StudioError("Unsupported video format")
    state["settings"] = {key: _string(cfg[key], key, 200) for key in ("aspect", "style", "camera", "animation", "resolution", "sound")}
    state["settings"].update(duration=duration, fps=fps)
    if len(json.dumps(state, ensure_ascii=False).encode("utf-8")) > _MAX_BYTES:
        raise StudioError("Studio project exceeds size limit")
    return state


class StudioStore:
    def __init__(self, workspace: str | Path, project: str = "mia_story"):
        if not _PROJECT.fullmatch(project):
            raise StudioError("Invalid project identifier")
        self.workspace = Path(workspace).expanduser().resolve()
        self.project = project
        self.root = self.workspace / project
        if self.root.is_symlink() or getattr(self.root, "is_junction", lambda: False)():
            raise StudioError("Project path cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.resolve().is_relative_to(self.workspace):
            raise StudioError("Project outside workspace")
        self.path = self.root / "studio_state.json"

    def load(self) -> dict[str, Any]:
        with _LOCK:
            if self.path.is_symlink():
                raise StudioError("Unsafe state path")
            if not self.path.exists():
                return self._import_existing_plan()
            if self.path.stat().st_size > _MAX_BYTES:
                raise StudioError("State file is too large")
            try:
                obj = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise StudioError("State file is unreadable or corrupt") from exc
            return validate_state(obj, self.project)

    def _import_existing_plan(self) -> dict[str, Any]:
        """Adopt an existing validated story plan without rewriting it or its assets."""
        result = default_state(self.project)
        plan_path = self.root / "story_plan.json"
        if plan_path.is_symlink() or not plan_path.is_file() or plan_path.stat().st_size > 48_000:
            return result
        try:
            plan = validate_story_plan(json.loads(plan_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, StoryPlanError):
            return result
        if plan["project_name"] != self.project:
            return result
        result["title"] = plan["title"]
        result["task"] = plan["logline"][:4000]
        people = plan.get("character_bible", {})
        if isinstance(people, dict):
            for key, value in list(people.items())[:59]:
                if not isinstance(key, str) or not key.strip():
                    continue
                name = key.strip()[:100]
                ch = next((c for c in result["characters"] if c["name"].casefold() == name.casefold()), None)
                if ch is None:
                    ch = {"id": f"char_import_{len(result['characters'])}", "name": name,
                          "role": "Персонаж", "age": "", "traits": "", "appearance": "",
                          "outfit": "", "voice": "", "reference": ""}
                    result["characters"].append(ch)
                if isinstance(value, dict):
                    ch["role"] = str(value.get("роль", ch["role"]))[:120]
                    ch["traits"] = str(value.get("характер", ""))[:900]
                    ch["appearance"] = str(value.get("внешность", ""))[:1200]
        indexed_props: dict[str, str] = {p["name"]: p["id"] for p in result["props"]}
        for index, scene in enumerate(plan["scenes"], 1):
            prop_ids = []
            for name in scene.get("assets", []):
                if name not in indexed_props and len(result["props"]) < 200:
                    prop_id = f"prop_import_{len(result['props'])}"
                    indexed_props[name] = prop_id
                    result["props"].append({"id": prop_id, "name": name[:120], "kind": "Реквизит",
                                            "description": "Импортировано из сценария", "reference": ""})
                if name in indexed_props and indexed_props[name] not in prop_ids:
                    prop_ids.append(indexed_props[name])
            scene_id = f"scene_{index:03d}"
            result["scenes"].append({"id": scene_id,
                                      "title": scene["title"], "prompt": scene["action"],
                                      "location": scene["location"], "camera": scene["camera"],
                                      "style": result["settings"]["style"],
                                      "animation": result["settings"]["animation"],
                                      "status": "план готов", "preview": "",
                                      "duration": scene["duration_seconds"],
                                      "characters": [], "props": prop_ids})
        if result["scenes"]:
            result["active_scene"] = result["scenes"][0]["id"]
        return validate_state(result, self.project)

    def save(self, raw: Any, expected_revision: int) -> dict[str, Any]:
        with _LOCK:
            current = self.load()
            if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or current["revision"] != expected_revision:
                raise StudioConflict("Project changed in another window; reload before saving")
            state = validate_state(raw, self.project)
            state["revision"] = current["revision"] + 1
            if self.path.is_symlink():
                raise StudioError("Unsafe state path")
            fd, temp = tempfile.mkstemp(prefix=".studio-", suffix=".tmp", dir=self.root)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                    json.dump(state, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, self.path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            return copy.deepcopy(state)


def to_story_plan(state: dict[str, Any]) -> dict[str, Any]:
    """Translate UI scenes into the existing inert validated story-plan contract."""
    project = state["project"]
    validated = validate_state(state, project)
    if not validated["scenes"]:
        raise StudioError("Create at least one scene before preparing a story plan")
    names = {x["id"]: x["name"] for x in validated["props"]}
    characters = {x["id"]: x for x in validated["characters"]}
    bible = {}
    for item in validated["characters"][:12]:
        bible[item["name"]] = {"роль": item["role"], "внешность": item["appearance"][:120], "характер": item["traits"][:120]}
    # The existing compiler has a strict 4 KB budget for the character bible.
    if len(json.dumps(bible, ensure_ascii=False)) > 3500:
        bible = {x["name"]: x["role"] for x in validated["characters"][:8]}
    scenes = []
    for item in validated["scenes"]:
        people = ", ".join(characters[c]["name"] for c in item["characters"])
        description = item["prompt"] or validated["task"] or item["title"]
        scenes.append({"scene_id": item["id"], "title": item["title"],
                       "duration_seconds": item["duration"],
                       "location": item["location"] or "Локация пока не задана",
                       "action": (description[:2900] + (". Герои: " + people if people else ""))[:3000],
                       "camera": item["camera"] or validated["settings"]["camera"],
                       "visual_prompt": description[:2000],
                       "assets": [names[p] for p in item["props"]],
                       "dialogue": []})
    total = sum(x["duration_seconds"] for x in scenes)
    plan = {"schema_version": 1, "project_name": project,
            "title": validated["title"],
            "logline": (validated["task"] or validated["title"])[:1200],
            "target_duration_seconds": max(5, total),
            "language": "ru", "character_bible": bible, "scenes": scenes}
    return validate_story_plan(plan)
