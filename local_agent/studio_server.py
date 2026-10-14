"""Loopback-only Blender studio UI (standard library; no cloud dependency)."""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import shutil
import hashlib
import sqlite3
from contextlib import contextmanager
import subprocess
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from local_agent.scene_compiler import compile_story_plan
from local_agent.story_plan import StoryPlanError, save_story_plan
from local_agent.studio_state import StudioConflict, StudioError, StudioStore, to_story_plan
from local_agent.studio_references import approved_status, approved_bytes, attach_approved_mia
from local_agent.studio_jobs import StudioJobs, StudioJobError
from local_agent.prompt_interpreter import interpret_scene, PromptError
from local_agent.octava_credentials import OctavaKeyError, key_status, replace_key as _replace_octava_key, set_default_model
from local_agent.mailbox_policy import (
    MailboxPolicyError, load_policy, save_policy,
    load_telegram_notifications, save_telegram_notifications,
    telegram_notifications_enabled,
    load_runtime_control, set_runtime_pause, request_runtime_restart,
    get_trusted_update_opt_in as get_opt_in,
    set_trusted_update_opt_in as set_opt_in,
)
from datetime import datetime, timezone
import tempfile
import time


def _octava_key_probe_transport(request, timeout=18):
    """A single bounded probe with actionable errors; never expose credentials."""
    import socket
    import ssl
    from urllib.error import HTTPError, URLError
    from urllib.request import urlopen
    try:
        # No automatic retry: a timed-out POST may already have been billed.
        return urlopen(request, timeout=60)
    except HTTPError:
        # The credential module already maps numeric HTTP status safely.
        raise
    except (URLError, TimeoutError, OSError) as exc:
        cause = exc.reason if isinstance(exc, URLError) else exc
        if isinstance(cause, ssl.SSLCertVerificationError):
            message = "OctavAPI: не прошла проверка TLS-сертификата. Проверьте дату/время Windows и HTTPS-перехват антивируса или прокси."
        elif isinstance(cause, ssl.SSLError):
            message = "OctavAPI: ошибка защищённого TLS-соединения."
        elif isinstance(cause, socket.gaierror):
            message = "OctavAPI: DNS не смог определить адрес сервера."
        elif isinstance(cause, (TimeoutError, socket.timeout)):
            message = "OctavAPI: сервер не завершил проверочный запрос за 60 секунд."
        elif isinstance(cause, ConnectionRefusedError):
            message = "OctavAPI: сетевое подключение отклонено сервером или прокси."
        elif isinstance(cause, ConnectionResetError):
            message = "OctavAPI: сетевое подключение сброшено сервером или прокси."
        else:
            message = "OctavAPI: сбой сетевого транспорта (" + type(cause).__name__ + ")."
        raise OctavaKeyError(message + " Новый ключ не сохранён; прежний ключ не изменён.") from None


def replace_key(value):
    """Validate the candidate once without changing existing failure semantics."""
    return _replace_octava_key(value, transport=_octava_key_probe_transport)


_STATIC = Path(__file__).resolve().parent / "studio_static"
_MEDIA_NAME = re.compile(r"[a-f0-9]{32}\.(?:png|jpg|webp)\Z")
_IMAGE_MIMES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
_MAX_REQUEST = 4_600_000


ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / ".local_agent" / "dropbox_review.json"
REVIEW_FOLDER = "AI-Agent-Reviews"
MAX_VIDEO_BYTES = 32_000_000
MAX_REVIEW_JOBS = 40
_JOB_RE = re.compile(r"[a-f0-9]{32}\Z")
_LOCK = threading.RLock()



_SEASON_HEADER = re.compile(r"(?m)^=== СЕРИЯ (\d{2}) \| ([^\r\n]+?) ===\s*$")
_EPISODE_MARKER = re.compile(r"(?m)^EPISODE_ID:\s*(S01E\d{2})\s*$")
_SCENE_HEADER = re.compile(r"(?m)^##\s+(S01E\d{2}_SC\d{2})\s+\|\s*([^\r\n]+?)\s*$")
_ASSET_ID = re.compile(r"\b(?:char|set|prop|fx)\.[A-Za-z0-9_.-]+\b")
_EPISODE_ID = re.compile(r"S01E(?:0[1-9]|[12]\d|30)\Z")
_EPISODE_DB_LOCK = threading.RLock()
_MAX_SEASON_BYTES = 1_000_000
_SEASON_DB = ROOT / ".local_agent" / "season_episodes.sqlite3"


@contextmanager
def _episode_db():
    folder = _SEASON_DB.parent
    if folder.is_symlink() or getattr(folder, "is_junction", lambda: False)():
        raise StudioError("Unsafe episode database directory")
    folder.mkdir(parents=True, exist_ok=True)
    if not folder.resolve().is_relative_to(ROOT.resolve()) or _SEASON_DB.is_symlink():
        raise StudioError("Unsafe episode database path")
    db = sqlite3.connect(_SEASON_DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS seasons (
            season_id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS episodes (
            season_id TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            episode_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            full_text TEXT NOT NULL,
            revision INTEGER NOT NULL,
            scenes_json TEXT NOT NULL,
            assets_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (season_id, episode_id),
            UNIQUE (season_id, episode_number),
            FOREIGN KEY (season_id) REFERENCES seasons(season_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS episode_revisions (
            season_id TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            full_text TEXT NOT NULL,
            saved_at TEXT NOT NULL,
            PRIMARY KEY (season_id, episode_id, revision),
            FOREIGN KEY (season_id, episode_id) REFERENCES episodes(season_id, episode_id) ON DELETE CASCADE
        );
    """)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def _parse_episode_block(block: str, number: int) -> dict:
    expected_id = f"S01E{number:02d}"
    header = _SEASON_HEADER.match(block)
    if not header or int(header.group(1)) != number:
        raise StudioError(f"Серия {number:02d}: отсутствует или неверен заголовок серии.")
    markers = list(_EPISODE_MARKER.finditer(block))
    if len(markers) != 1 or markers[0].group(1) != expected_id:
        raise StudioError(f"Серия {number:02d}: ожидается уникальный ID {expected_id}.")
    scene_matches = list(_SCENE_HEADER.finditer(block))
    scene_ids = [match.group(1) for match in scene_matches]
    minimum_scene_count = 4 if number == 26 else 5
    if len(scene_ids) < minimum_scene_count:
        raise StudioError(
            f"{expected_id}: нужно не менее {minimum_scene_count} сцен с отдельными ID."
        )
    expected_scenes = [f"{expected_id}_SC{index:02d}" for index in range(1, len(scene_ids) + 1)]
    if scene_ids != expected_scenes:
        raise StudioError(f"{expected_id}: ID сцен должны быть уникальны и идти по порядку.")
    scenes = []
    assets = set()
    for index, match in enumerate(scene_matches):
        end = scene_matches[index + 1].start() if index + 1 < len(scene_matches) else len(block)
        scene_text = block[match.start():end]
        scene_assets = sorted(set(_ASSET_ID.findall(scene_text)))
        assets.update(scene_assets)
        scenes.append({
            "scene_id": match.group(1),
            "title": match.group(2).strip(),
            "asset_ids": scene_assets,
        })
    return {
        "episode_id": expected_id,
        "episode_number": number,
        "title": header.group(2).strip(),
        "full_text": block.strip(),
        "scenes": scenes,
        "asset_ids": sorted(assets),
    }


def parse_season_screenplay(text: str) -> list[dict]:
    if not isinstance(text, str) or not text.strip():
        raise StudioError("Файл сценария пуст.")
    if "\x00" in text or len(text.encode("utf-8")) > _MAX_SEASON_BYTES:
        raise StudioError("Сценарий содержит недопустимые данные или превышает 1 МБ.")
    headers = list(_SEASON_HEADER.finditer(text))
    numbers = [int(match.group(1)) for match in headers]
    duplicates = sorted({number for number in numbers if numbers.count(number) > 1})
    if duplicates:
        raise StudioError("Повторяются номера серий: " + ", ".join(f"{n:02d}" for n in duplicates))
    missing = sorted(set(range(1, 31)) - set(numbers))
    extra = sorted(set(numbers) - set(range(1, 31)))
    if missing or extra or len(headers) != 30:
        details = []
        if missing:
            details.append("не хватает серий " + ", ".join(f"{n:02d}" for n in missing))
        if extra:
            details.append("лишние номера " + ", ".join(str(n) for n in extra))
        raise StudioError("Нужно ровно 30 серий по порядку; " + "; ".join(details or ["найдены некорректные заголовки"]))
    if numbers != list(range(1, 31)):
        raise StudioError("Серии должны идти в порядке от 01 до 30.")
    episodes = []
    for index, match in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        episodes.append(_parse_episode_block(text[match.start():end], index + 1))
    return episodes


def import_season_screenplay(filename: str, raw: bytes) -> dict:
    if (not isinstance(filename, str) or Path(filename).name != filename
            or "/" in filename or "\\" in filename or not filename.lower().endswith(".txt")):
        raise StudioError("Выберите обычный файл с расширением .txt.")
    if not isinstance(raw, bytes) or not raw or len(raw) > _MAX_SEASON_BYTES:
        raise StudioError("Файл сценария пуст или превышает 1 МБ.")
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise StudioError("Не удалось прочитать сценарий: сохраните TXT в кодировке UTF-8.") from exc
    episodes = parse_season_screenplay(text)
    checksum = hashlib.sha256(raw).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    with _EPISODE_DB_LOCK, _episode_db() as db:
        existing = db.execute("SELECT source_sha256 FROM seasons WHERE season_id='S01'").fetchone()
        if existing:
            if existing["source_sha256"] != checksum:
                raise StudioConflict("Первый сезон уже импортирован. Измените отдельную серию или восстановите её из истории.")
            return {"season_id": "S01", "source_sha256": checksum, "episodes": 30, "already_imported": True}
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO seasons VALUES(?,?,?,?)", ("S01", filename, checksum, now))
        for episode in episodes:
            db.execute(
                "INSERT INTO episodes VALUES(?,?,?,?,?,?,?,?,?)",
                ("S01", episode["episode_id"], episode["episode_number"], episode["title"],
                 episode["full_text"], 1, json.dumps(episode["scenes"], ensure_ascii=False),
                 json.dumps(episode["asset_ids"], ensure_ascii=False), now),
            )
            db.execute(
                "INSERT INTO episode_revisions VALUES(?,?,?,?,?)",
                ("S01", episode["episode_id"], 1, episode["full_text"], now),
            )
    return {"season_id": "S01", "source_sha256": checksum, "episodes": 30, "already_imported": False}



def get_season_episode_history(episode_id: str) -> list[dict]:
    if not isinstance(episode_id, str) or not _EPISODE_ID.fullmatch(episode_id):
        raise StudioError("Некорректный ID серии.")
    with _EPISODE_DB_LOCK, _episode_db() as db:
        rows = db.execute(
            "SELECT revision, full_text, saved_at FROM episode_revisions "
            "WHERE season_id='S01' AND episode_id=? ORDER BY revision DESC",
            (episode_id,),
        ).fetchall()
    return [{"revision": row["revision"], "full_text": row["full_text"], "saved_at": row["saved_at"]}
            for row in rows]


def _episode_asset_readiness(episode: dict, store: StudioStore) -> dict:
    registered = {}
    try:
        from local_agent.asset_registry import read_asset_registry
        registered = read_asset_registry(store.root, store.project)
    except (ImportError, OSError, ValueError):
        registered = {}
    mia_reference_ready = False
    try:
        mia_reference_ready = approved_status(store.workspace).get("status") == "ready"
    except (StudioError, OSError, ValueError):
        pass
    assets = []
    for asset_id in episode["asset_ids"]:
        image_url = ""
        if asset_id == "char.mia.master" and mia_reference_ready:
            status, path = "approved_reference", "/api/approved-reference-image/mia"
            image_url = path
        elif asset_id in registered:
            path = registered[asset_id]["path"]
            status = "draft" if path.replace("\\", "/").startswith("assets/references/drafts/") else "registered"
            if Path(path).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                image_url = "/api/asset-image/" + asset_id
        else:
            status, path = "missing", ""
        assets.append({"asset_id": asset_id, "status": status, "path": path,
                       "image_url": image_url})
    missing = [asset["asset_id"] for asset in assets if asset["status"] == "missing"]
    drafts = [asset["asset_id"] for asset in assets if asset["status"] == "draft"]
    return {
        "assets": assets,
        "missing_assets": missing + drafts,
        "draft_assets": drafts,
        "reference_readiness": "blocked_missing_references" if missing else
                               "blocked_draft_references" if drafts else "references_present",
        "animation_readiness": "not_verified",
    }


def _asset_reference_image(store: StudioStore, asset_id: str) -> tuple[bytes, str] | None:
    if not isinstance(asset_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", asset_id):
        return None
    if asset_id == "char.mia.master":
        raw = approved_bytes(store.workspace)
        return (raw, "image/jpeg") if raw else None
    try:
        from local_agent.asset_registry import read_asset_registry
        registered = read_asset_registry(store.root, store.project)
    except (ImportError, OSError, ValueError):
        return None
    item = registered.get(asset_id)
    if not isinstance(item, dict):
        return None
    relative = item.get("path")
    if not isinstance(relative, str):
        return None
    relpath = Path(relative)
    if relpath.is_absolute() or any(part in ("", ".", "..") for part in relpath.parts):
        return None
    project = store.root.resolve()
    assets_root = (project / "assets").resolve()
    candidate = project / relpath
    current = candidate
    try:
        while current != project:
            if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
                return None
            current = current.parent
        resolved = candidate.resolve(strict=True)
        if (not resolved.is_relative_to(assets_root) or not resolved.is_file()
                or resolved.stat().st_size > 15_000_000):
            return None
        raw = resolved.read_bytes()
    except (OSError, RuntimeError):
        return None
    ext = resolved.suffix.lower()
    if ext == ".png" and raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return raw, "image/png"
    if ext in (".jpg", ".jpeg") and raw.startswith(b"\xff\xd8\xff"):
        return raw, "image/jpeg"
    if ext == ".webp" and len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return raw, "image/webp"
    return None


def list_season_asset_library(store: StudioStore) -> dict:
    season = list_season_episodes()
    assets = {}
    for episode in season["episodes"]:
        readiness = _episode_asset_readiness(episode, store)
        by_id = {item["asset_id"]: item for item in readiness["assets"]}
        for asset_id in episode["asset_ids"]:
            item = by_id[asset_id]
            category = asset_id.split(".", 1)[0]
            current = assets.setdefault(asset_id, {
                "asset_id": asset_id,
                "category": {"char": "characters", "set": "environments",
                             "prop": "props", "fx": "effects"}.get(category, "other"),
                "status": item["status"],
                "image_url": item.get("image_url", ""),
                "review_status": "approved" if item["status"] == "approved_reference" else
                                 "draft" if item["status"] == "draft" else
                                 "unverified" if item["status"] == "registered" else "missing",
                "episodes": [],
                "scenes": [],
            })
            current["episodes"].append(episode["episode_id"])
            for scene in episode["scenes"]:
                if asset_id in scene["asset_ids"]:
                    current["scenes"].append(scene["scene_id"])
    try:
        from local_agent.asset_registry import read_asset_registry
        registered = read_asset_registry(store.root, store.project)
    except (ImportError, OSError, ValueError, TypeError):
        registered = {}
    for asset_id, item in registered.items():
        relative = str(item.get("path", "")).replace("\\", "/")
        if (asset_id in assets or not relative.startswith("assets/references/drafts/")
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", asset_id)):
            continue
        category = asset_id.split(".", 1)[0]
        assets[asset_id] = {
            "asset_id": asset_id,
            "category": {"char": "characters", "set": "environments",
                         "prop": "props", "fx": "effects"}.get(category, "other"),
            "status": "draft",
            "image_url": "/api/asset-image/" + asset_id,
            "review_status": "draft",
            "episodes": [],
            "scenes": [],
        }
    return {"assets": sorted(assets.values(), key=lambda item: (item["category"], item["asset_id"]))}


def save_season_asset_draft(store: StudioStore, asset_id: str, raw: bytes,
                            extension: str) -> dict:
    """Save one validated generated reference as a non-overwriting local draft."""
    from local_agent.asset_registry import (
        AssetRegistryError, read_asset_registry, scan_project_assets,
    )
    if asset_id != "char.mia.master.luna_draft":
        raise StudioError("Only the fixed Luna Mia draft asset ID is allowed")
    if extension != "png" or not isinstance(raw, bytes) or not 0 < len(raw) <= 15_000_000:
        raise StudioError("Generated draft must be a PNG no larger than 15 MB")
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise StudioError("Generated draft PNG signature is invalid")
    import struct
    import zlib
    if (len(raw) < 45 or raw[8:12] != b"\x00\x00\x00\x0d"
            or raw[12:16] != b"IHDR" or b"IDAT" not in raw[33:-12]
            or raw[-12:-8] != b"\x00\x00\x00\x00" or raw[-8:-4] != b"IEND"):
        raise StudioError("Generated draft PNG structure is invalid")
    width, height = struct.unpack(">II", raw[16:24])
    if (width, height) != (1024, 1024):
        raise StudioError("Generated draft must be exactly 1024x1024 pixels")
    if (zlib.crc32(raw[12:29]) & 0xffffffff) != int.from_bytes(raw[29:33], "big"):
        raise StudioError("Generated draft PNG header checksum is invalid")
    if (zlib.crc32(b"IEND") & 0xffffffff) != int.from_bytes(raw[-4:], "big"):
        raise StudioError("Generated draft PNG ending checksum is invalid")
    workspace = Path(store.workspace).expanduser().resolve()
    project = workspace / store.project
    if (project.is_symlink() or getattr(project, "is_junction", lambda: False)()
            or not project.is_dir() or not project.resolve().is_relative_to(workspace)):
        raise StudioError("Project directory is unsafe")
    assets_root = project / "assets"
    for folder in (assets_root, assets_root / "references", assets_root / "references" / "drafts"):
        if folder.is_symlink() or getattr(folder, "is_junction", lambda: False)():
            raise StudioError("Draft asset directory must not be a symlink or junction")
        folder.mkdir(exist_ok=True)
    destination = assets_root / "references" / "drafts" / (asset_id + ".png")
    if destination.is_symlink() or getattr(destination, "is_junction", lambda: False)():
        raise StudioError("Draft asset destination is unsafe")
    try:
        registered = read_asset_registry(project, store.project)
    except (OSError, ValueError, TypeError, AssetRegistryError):
        registered = {}
    if asset_id in registered or destination.exists():
        raise StudioError("Draft asset already exists; refusing to overwrite")
    try:
        with destination.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        scan_project_assets(workspace, store.project)
        verified = read_asset_registry(project, store.project).get(asset_id)
        if not verified or verified.get("path") != destination.relative_to(project).as_posix():
            raise StudioError("Draft asset registry verification failed")
    except (OSError, AssetRegistryError, ValueError) as exc:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(exc, StudioError):
            raise
        raise StudioError("Could not safely register generated draft") from exc
    return {
        "asset_id": asset_id,
        "path": destination.relative_to(project).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "image_url": "/api/asset-image/" + asset_id,
    }


def _episode_row_json(row, *, include_text: bool = False) -> dict:
    result = {
        "episode_id": row["episode_id"],
        "episode_number": row["episode_number"],
        "title": row["title"],
        "revision": row["revision"],
        "scenes": json.loads(row["scenes_json"]),
        "asset_ids": json.loads(row["assets_json"]),
        "updated_at": row["updated_at"],
    }
    if include_text:
        result["full_text"] = row["full_text"]
    return result


def list_season_episodes() -> dict:
    with _EPISODE_DB_LOCK, _episode_db() as db:
        season = db.execute("SELECT * FROM seasons WHERE season_id='S01'").fetchone()
        if not season:
            return {"season_id": "S01", "imported": False, "episodes": []}
        rows = db.execute("SELECT * FROM episodes WHERE season_id='S01' ORDER BY episode_number").fetchall()
    return {
        "season_id": "S01", "imported": True, "source_filename": season["filename"],
        "source_sha256": season["source_sha256"],
        "episodes": [_episode_row_json(row) for row in rows],
    }


def get_season_episode(episode_id: str) -> dict:
    if not isinstance(episode_id, str) or not _EPISODE_ID.fullmatch(episode_id):
        raise StudioError("Некорректный ID серии.")
    with _EPISODE_DB_LOCK, _episode_db() as db:
        row = db.execute("SELECT * FROM episodes WHERE season_id='S01' AND episode_id=?", (episode_id,)).fetchone()
    if not row:
        raise StudioError("Серия не найдена.")
    return _episode_row_json(row, include_text=True)


def edit_season_episode(episode_id: str, revision: int, text: str) -> dict:
    if not isinstance(episode_id, str) or not _EPISODE_ID.fullmatch(episode_id):
        raise StudioError("Некорректный ID серии.")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise StudioError("Некорректная ревизия серии.")
    if not isinstance(text, str) or len(text.encode("utf-8")) > 100_000:
        raise StudioError("Текст серии должен быть не больше 100 КБ.")
    number = int(episode_id[-2:])
    episode = _parse_episode_block(text, number)
    if episode["episode_id"] != episode_id:
        raise StudioError("ID текста не совпадает с выбранной серией.")
    now = datetime.now(timezone.utc).isoformat()
    with _EPISODE_DB_LOCK, _episode_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT revision FROM episodes WHERE season_id='S01' AND episode_id=?",
            (episode_id,),
        ).fetchone()
        if not row:
            raise StudioError("Серия не найдена.")
        if row["revision"] != revision:
            raise StudioConflict("Серия изменилась в другом окне. Перезагрузите её перед сохранением.")
        next_revision = revision + 1
        db.execute("INSERT INTO episode_revisions VALUES(?,?,?,?,?)",
                   ("S01", episode_id, next_revision, episode["full_text"], now))
        db.execute(
            "UPDATE episodes SET title=?, full_text=?, revision=?, scenes_json=?, assets_json=?, updated_at=? "
            "WHERE season_id='S01' AND episode_id=?",
            (episode["title"], episode["full_text"], next_revision,
             json.dumps(episode["scenes"], ensure_ascii=False),
             json.dumps(episode["asset_ids"], ensure_ascii=False), now, episode_id),
        )
        row = db.execute("SELECT * FROM episodes WHERE season_id='S01' AND episode_id=?", (episode_id,)).fetchone()
    return _episode_row_json(row, include_text=True)

_OCTAVA_RESUME_LOCK = threading.Lock()


def _resume_octava_waiting_projects(workspace: Path) -> None:
    """Best-effort one-shot resume; all durable state remains in local files.

    Only sessions paused due to invalid/exhausted keys are retried, never
    arbitrary code, shell commands or third-party tool calls.
    """
    if not _OCTAVA_RESUME_LOCK.acquire(blocking=False):
        return
    try:
        from local_agent.mailbox_policy import OctavaProjectMemory, MemoryErrorSafe
        from local_agent.octava_advisor import OctavaAdviceError
        from local_agent.poller import _run_octava_advice
        try:
            policy = load_policy()
            if not (policy["enabled"] and policy["allow_octava"]):
                return
            projects = OctavaProjectMemory.waiting_projects(workspace, limit=3)
        except (MemoryErrorSafe, MailboxPolicyError):
            return
        # Explicit workspace: never mutate process-global environment from a thread.
        for project_id in projects:
            try:
                _run_octava_advice({"project_id": project_id, "resume_pending": True},
                                   workspace=str(workspace))
            except (OctavaAdviceError, MemoryErrorSafe):
                continue  # preserved for later explicit resume
    finally:
        _OCTAVA_RESUME_LOCK.release()


class ReviewDeliveryError(ValueError):
    pass


def _safe_path(path: Path) -> Path:
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ReviewDeliveryError("Unsafe Dropbox path or junction")
    return path


def read_settings() -> dict[str, bool]:
    with _LOCK:
        _safe_path(SETTINGS.parent)
        _safe_path(SETTINGS)
        try:
            raw = SETTINGS.read_bytes()
        except FileNotFoundError:
            return {"enabled": False}
        if len(raw) > 256:
            raise ReviewDeliveryError("Invalid Dropbox review setting length")
        try:
            obj = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ReviewDeliveryError("Invalid Dropbox review settings") from exc
        if not isinstance(obj, dict) or set(obj) != {"enabled"} or type(obj["enabled"]) is not bool:
            raise ReviewDeliveryError("Invalid Dropbox review permission")
        return obj


def save_settings(value: dict[str, bool]) -> dict[str, bool]:
    if not isinstance(value, dict) or set(value) != {"enabled"} or type(value["enabled"]) is not bool:
        raise ReviewDeliveryError("Expected an enabled boolean")
    with _LOCK:
        _safe_path(SETTINGS.parent)
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        _safe_path(SETTINGS)
        with tempfile.NamedTemporaryFile(prefix=".dropbox-review-", suffix=".tmp",
                                         dir=SETTINGS.parent, delete=False) as f:
            name = Path(f.name)
            f.write((json.dumps(value) + "\n").encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        try:
            os.replace(name, SETTINGS)
        finally:
            name.unlink(missing_ok=True)
    return value


def discover_dropbox_root() -> Path | None:
    """Locate a real Windows Dropbox Desktop sync root without network tokens.

    Prefer Dropbox's own account metadata. Some Windows Desktop builds store
    info.json under LOCALAPPDATA instead of APPDATA. If the metadata is absent,
    consider only standard Dropbox folder names under the current user profile,
    AND only when the review folder that was created in Dropbox cloud already
    exists. Never create or blindly assume a new folder is cloud-synced.
    """
    override = os.environ.get("LOCAL_AGENT_DROPBOX_ROOT", "").strip()
    if override:
        candidate = Path(override).expanduser()
        _safe_path(candidate)
        if not candidate.is_dir():
            return None
        return candidate.resolve()

    configs = []
    for env in ("APPDATA", "LOCALAPPDATA"):
        base = os.environ.get(env, "").strip()
        if base:
            configs.append(Path(base) / "Dropbox" / "info.json")
    for config in configs:
        if not config.is_file() or config.is_symlink() or config.stat().st_size > 65_536:
            continue
        try:
            obj = json.loads(config.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                for account in ("personal", "business"):
                    info = obj.get(account)
                    if isinstance(info, dict) and isinstance(info.get("path"), str):
                        candidate = Path(info["path"])
                        _safe_path(candidate)
                        if candidate.is_dir():
                            return candidate.resolve()
        except (OSError, ValueError, TypeError, ReviewDeliveryError):
            continue

    if os.name == "nt":
        home = Path.home()
        matches = []
        for name in ("Dropbox", "Dropbox (Personal)", "Dropbox (Business)"):
            candidate = home / name
            reviews = candidate / REVIEW_FOLDER
            if (candidate.is_dir() and reviews.is_dir()
                    and not candidate.is_symlink() and not reviews.is_symlink()
                    and not getattr(candidate, "is_junction", lambda: False)()
                    and not getattr(reviews, "is_junction", lambda: False)()):
                matches.append(candidate.resolve())
        if len(matches) == 1:
            return matches[0]
    return None

def review_status() -> dict[str, Any]:
    permitted = read_settings()["enabled"]
    path = discover_dropbox_root()
    return {"enabled": permitted, "desktop_folder_detected": path is not None,
            "sync_verified": False, "folder_name": REVIEW_FOLDER,
            "note": "Actual cloud sync must be confirmed by checking Dropbox."}


def _ffmpeg(cmd: list[str], *, timeout: int) -> None:
    try:
        p = subprocess.run(cmd, shell=False, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReviewDeliveryError("FFmpeg export could not finish") from exc
    if p.returncode:
        raise ReviewDeliveryError("FFmpeg preview export failed")


def export_review(job_dir: Path, job_info: dict[str, Any], ffmpeg: str) -> dict[str, Any]:
    """Export a bounded video, contact sheet and technical manifest into Dropbox Sync.

    The completion marker is written last. Existing review folders are never overwritten.
    A failure must not change the status of the successful original Blender render.
    """
    if not read_settings()["enabled"]:
        return {"status": "disabled"}
    job_id = job_info.get("job_id")
    if not isinstance(job_id, str) or not _JOB_RE.fullmatch(job_id):
        raise ReviewDeliveryError("Invalid render job ID")
    src = _safe_path(job_dir / "scene.mp4")
    if not src.is_file() or src.stat().st_size < 100:
        raise ReviewDeliveryError("No completed scene.mp4")
    root = discover_dropbox_root()
    if root is None:
        raise ReviewDeliveryError("Dropbox Desktop folder was not detected; sign in to Dropbox desktop")
    review_root = _safe_path(root / REVIEW_FOLDER)
    review_root.mkdir(exist_ok=True)
    entries = list(review_root.iterdir())
    if len(entries) >= MAX_REVIEW_JOBS:
        raise ReviewDeliveryError("Review folder limit reached; manually archive older reviews")
    destination = _safe_path(review_root / job_id)
    if destination.exists():
        raise ReviewDeliveryError("Review job already exists; refusing to overwrite")
    destination.mkdir()
    try:
        video = destination / "preview.mp4"
        if src.stat().st_size <= MAX_VIDEO_BYTES:
            shutil.copyfile(src, video)
        else:
            _ffmpeg([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                     "-i", str(src), "-vf", "scale=480:-2:force_original_aspect_ratio=decrease",
                     "-an", "-r", "12", "-c:v", "libx264", "-preset", "veryfast",
                     "-crf", "32", "-pix_fmt", "yuv420p", str(video)], timeout=300)
        if video.stat().st_size > MAX_VIDEO_BYTES:
            raise ReviewDeliveryError("Review video still exceeds 32 MB after compression")
        sheet = destination / "frames.jpg"
        total_frames = job_info.get("total_frames")
        if type(total_frames) is int and 12 <= total_frames <= 60_000:
            stride = max(1, total_frames // 12)
            vf = f"select='not(mod(n\,{stride}))',scale=180:-2,tile=4x3"
        else:
            vf = "fps=1,scale=180:-2,tile=4x3"
        _ffmpeg([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-i", str(video), "-vf", vf,
                 "-frames:v", "1", "-q:v", "4", str(sheet)], timeout=90)
        if not sheet.is_file() or sheet.stat().st_size < 150:
            raise ReviewDeliveryError("Contact sheet is missing")
        plan_file = job_dir / "manifest.json"
        plan = {}
        if plan_file.is_file() and not plan_file.is_symlink():
            try:
                plan = json.loads(plan_file.read_text("utf-8"))
                if not isinstance(plan, dict):
                    plan = {}
            except (OSError, ValueError, UnicodeError):
                plan = {}
        details = {
            "job_id": job_id,
            "render_type": job_info.get("kind"),
            "scene_id": job_info.get("scene_id"),
            "fps": plan.get("fps"),
            "duration_seconds": plan.get("duration"),
            "camera": plan.get("camera") if isinstance(plan.get("camera"), (str, dict)) else None,
            "frame_count": job_info.get("total_frames"),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "files": ["preview.mp4", "frames.jpg"],
        }
        packed = json.dumps(details, ensure_ascii=False, indent=2)
        if len(packed.encode("utf-8")) > 8192:
            details["camera"] = None
            packed = json.dumps(details, ensure_ascii=False, indent=2)
        (destination / "camera.json").write_text(packed + "\n", encoding="utf-8")
        (destination / "complete.json").write_text(
            json.dumps({"status": "completed", "job_id": job_id}) + "\n", encoding="utf-8")
        return {"status": "exported_to_local_dropbox", "folder": REVIEW_FOLDER + "/" + job_id,
                "files": ["preview.mp4", "frames.jpg", "camera.json", "complete.json"],
                "cloud_sync_verified": False}
    except BaseException:
        # Only this newly-created job folder; never delete user-owned existing content.
        shutil.rmtree(destination, ignore_errors=True)
        raise




# Telegram alerts are explicitly opt-in and use the already-installed Windows
# Credential Manager. Never put a BotFather token in source, GitHub, logs or JSON.
_TELEGRAM_TOKEN_TARGET = "LocalAgent/Telegram/bot-token"
_TELEGRAM_CHAT_TARGET = "LocalAgent/Telegram/private-chat-id"
_TELEGRAM_TOKEN_RE = re.compile(r"[0-9]{5,15}:[A-Za-z0-9_-]{20,128}\Z")
_TELEGRAM_LOCK = threading.RLock()
_TELEGRAM_OUTBOX = ROOT / ".local_agent" / "telegram_outbox"

_TELEGRAM_TRANSPORT = ROOT / ".local_agent" / "telegram_transport.json"
_TELEGRAM_RELAY_URL = "https://octava-telegram-relay.onrender.com/api/telegram"


def telegram_transport_settings() -> dict[str, bool]:
    path = _TELEGRAM_TRANSPORT
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise TelegramAlertError("Недопустимая конфигурация Telegram")
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {"use_relay": False}
    except OSError:
        raise TelegramAlertError("Не удалось прочитать настройки Telegram") from None
    if len(raw) > 160:
        raise TelegramAlertError("Некорректные настройки Telegram")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise TelegramAlertError("Некорректные настройки Telegram") from None
    if not isinstance(value, dict) or set(value) != {"use_relay"} or type(value["use_relay"]) is not bool:
        raise TelegramAlertError("Некорректные настройки Telegram")
    return value


def telegram_set_transport(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {"use_relay"} or type(value["use_relay"]) is not bool:
        raise TelegramAlertError("Ожидается флаг use_relay")
    path = _TELEGRAM_TRANSPORT
    if path.parent.is_symlink() or path.is_symlink():
        raise TelegramAlertError("Недопустимая папка конфигурации")
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    with _TELEGRAM_LOCK:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".telegram-route-",
                                         suffix=".tmp", delete=False, mode="w",
                                         encoding="utf-8") as output:
            temp_path = Path(output.name)
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)
    return {"use_relay": value["use_relay"], "relay_provider": "Render",
            "note": "При включении бот-токен и сообщения передаются через ваш HTTPS-сервис Render"}



class TelegramAlertError(ValueError):
    pass


def _telegram_credentials() -> tuple[str | None, str | None]:
    if os.name != "nt":
        return (None, None)
    from local_agent.windows_credentials import CredentialStoreError, read_credential
    try:
        token = read_credential(target=_TELEGRAM_TOKEN_TARGET)
        chat = read_credential(target=_TELEGRAM_CHAT_TARGET)
    except CredentialStoreError:
        raise TelegramAlertError("Защищённое хранилище Windows недоступно") from None
    return token, chat


def telegram_status() -> dict[str, bool]:
    token, chat = _telegram_credentials()
    try:
        notices = load_telegram_notifications()["enabled"]
    except MailboxPolicyError as exc:
        raise TelegramAlertError(str(exc)) from None
    return {"configured": bool(token), "paired": bool(token and chat),
            "outbound_only": True, "enabled": bool(token and chat and notices),
            "notifications_enabled": notices,
            "use_relay": telegram_transport_settings()["use_relay"]}


def telegram_set_notifications(data: dict) -> dict[str, bool]:
    """Local-only switch. Disabling also drops undelivered old notices."""
    with _TELEGRAM_LOCK:
        try:
            result = save_telegram_notifications(data)
        except MailboxPolicyError as exc:
            raise TelegramAlertError(str(exc)) from None
        if not result["enabled"]:
            # Pending messages must not appear unexpectedly if alerts are re-enabled.
            if _TELEGRAM_OUTBOX.is_dir() and not _TELEGRAM_OUTBOX.is_symlink():
                for path in _TELEGRAM_OUTBOX.glob("*.json"):
                    if path.is_file() and not path.is_symlink():
                        try:
                            path.unlink(missing_ok=True)
                        except OSError:
                            pass
        return {"notifications_enabled": result["enabled"]}


def _telegram_call(token: str, method: str, data: dict, *, timeout: int = 10) -> dict:
    """Fixed HTTPS origin, fixed allowlisted Telegram Bot API methods."""
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
    if method not in ("getMe", "getUpdates", "sendMessage"):
        raise TelegramAlertError("Недопустимая операция Telegram")
    if not isinstance(token, str) or not _TELEGRAM_TOKEN_RE.fullmatch(token):
        raise TelegramAlertError("Неверный формат токена Telegram-бота")
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    if telegram_transport_settings()["use_relay"]:
        # Separate owner's HTTPS service is an explicit local opt-in. Unlike the
        # direct Telegram route, Render receives the bot token and message body.
        url = _TELEGRAM_RELAY_URL
        timeout = max(timeout, 45)  # Free Render services can cold-start slowly.
        payload = json.dumps({"token": token, "method": method, "params": data},
                             ensure_ascii=False).encode("utf-8")
    else:
        url = "https://api.telegram.org/bot" + token + "/" + method
    request = Request(url, method="POST", data=payload,
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(262145)
    except HTTPError as exc:
        # Never include the URL or response text, which can contain the token.
        raise TelegramAlertError("Telegram вернул HTTP " + str(exc.code)) from None
    except (URLError, TimeoutError, OSError):
        raise TelegramAlertError("Не удалось связаться с Telegram") from None
    if len(raw) > 262144:
        raise TelegramAlertError("Ответ Telegram слишком большой")
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict) or obj.get("ok") is not True:
            raise ValueError("bad response")
        return obj
    except (ValueError, UnicodeError):
        raise TelegramAlertError("Некорректный ответ Telegram") from None


def telegram_save_token(data: dict) -> dict:
    """Verify BotFather token via getMe, then save in Windows vault only."""
    from local_agent.windows_credentials import CredentialStoreError, write_credential, delete_credential
    if os.name != "nt":
        raise TelegramAlertError("Подключение Telegram доступно только в Windows Studio")
    token = data.get("bot_token")
    if not isinstance(data, dict) or set(data) != {"bot_token"} or not isinstance(token, str):
        raise TelegramAlertError("Укажите токен Telegram-бота")
    token = token.strip()
    if not _TELEGRAM_TOKEN_RE.fullmatch(token):
        raise TelegramAlertError("Проверьте токен BotFather")
    payload = _telegram_call(token, "getMe", {})
    bot = payload.get("result")
    if not isinstance(bot, dict) or bot.get("is_bot") is not True:
        raise TelegramAlertError("Telegram не подтвердил бота")
    try:
        # Changing the token must revoke pairing with the previous bot.
        write_credential(token, target=_TELEGRAM_TOKEN_TARGET)
        delete_credential(target=_TELEGRAM_CHAT_TARGET)
    except CredentialStoreError:
        raise TelegramAlertError("Не удалось сохранить Telegram в Windows") from None
    return {"configured": True, "paired": False, "enabled": False,
            "bot_username": str(bot.get("username", ""))[:80],
            "next_step": "Напишите /start созданному боту и нажмите Привязать чат"}


def telegram_pair_chat(data: dict) -> dict:
    from local_agent.windows_credentials import CredentialStoreError, write_credential
    if data != {}:
        raise TelegramAlertError("Не указывайте идентификаторы чатов вручную")
    token, _ = _telegram_credentials()
    if not token:
        raise TelegramAlertError("Сначала сохраните токен бота")
    recent = _telegram_call(token, "getUpdates", {"limit": 100, "timeout": 0})
    now = int(time.time())
    candidates: set[str] = set()
    for update in recent.get("result", []):
        if not isinstance(update, dict):
            continue
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        chat, sender = message.get("chat"), message.get("from")
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            continue
        if chat.get("type") != "private" or chat.get("id") != sender.get("id"):
            continue
        txt, stamp = message.get("text"), message.get("date")
        if (isinstance(txt, str) and txt.split(" ", 1)[0].split("@", 1)[0] == "/start"
                and type(stamp) is int and 0 <= now - stamp <= 900):
            candidates.add(str(chat["id"]))
    if len(candidates) != 1:
        raise TelegramAlertError(
            "Нужен один личный чат: отправьте боту /start и повторите через 15 секунд"
            if not candidates else "Обнаружено несколько чатов. Создайте отдельного бота для личных уведомлений")
    chat_id = next(iter(candidates))
    _telegram_call(token, "sendMessage",
                   {"chat_id": chat_id, "text": "Blender AI Agent подключён. Тестовое уведомление доставлено."})
    try:
        write_credential(chat_id, target=_TELEGRAM_CHAT_TARGET)
    except CredentialStoreError:
        raise TelegramAlertError("Не удалось закрепить личный Telegram-чат в Windows") from None
    return telegram_status()


def _telegram_outbox_dir() -> Path:
    parent = _TELEGRAM_OUTBOX.parent
    if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
        raise TelegramAlertError("Недопустимая папка уведомлений")
    if _TELEGRAM_OUTBOX.is_symlink() or getattr(_TELEGRAM_OUTBOX, "is_junction", lambda: False)():
        raise TelegramAlertError("Недопустимая очередь уведомлений")
    _TELEGRAM_OUTBOX.mkdir(parents=True, exist_ok=True)
    return _TELEGRAM_OUTBOX


def telegram_queue_event(event_id: str, message: str) -> bool:
    """Queue a bounded, idempotent local event, even while Telegram is offline."""
    import hashlib
    if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,120}", event_id):
        return False
    if not isinstance(message, str) or not 1 <= len(message) <= 600:
        return False
    try:
        token, chat = _telegram_credentials()
        if not token or not chat:
            return False
        with _TELEGRAM_LOCK:
            if not telegram_notifications_enabled():
                return False
            outbox = _telegram_outbox_dir()
            if len(list(outbox.glob("*.json"))) >= 100:
                return False
            digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
            target = outbox / (digest + ".json")
            if not target.is_file():
                with target.open("x", encoding="utf-8") as file:
                    json.dump({"event": event_id, "message": message,
                               "timestamp": int(time.time())}, file, ensure_ascii=False)
            return True
    except (OSError, ValueError, TelegramAlertError):
        return False


def telegram_flush_outbox(*, max_messages: int = 4) -> int:
    """Read a few queued notices and deliver them to one locally paired chat."""
    try:
        token, chat = _telegram_credentials()
        if not token or not chat or not _TELEGRAM_OUTBOX.is_dir():
            return 0
        count = 0
        with _TELEGRAM_LOCK:
            if not telegram_notifications_enabled():
                return 0
            for path in sorted(_TELEGRAM_OUTBOX.glob("*.json"))[:max_messages]:
                if path.is_symlink() or path.stat().st_size > 2048:
                    continue
                try:
                    event = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(event, dict) or set(event) != {"event", "message", "timestamp"}:
                        continue
                    if time.time() - event["timestamp"] > 604800:
                        path.unlink(missing_ok=True)
                        continue
                    _telegram_call(token, "sendMessage", {"chat_id": chat, "text": event["message"]}, timeout=8)
                    path.unlink()
                    count += 1
                except TelegramAlertError:
                    break
                except (OSError, ValueError, TypeError, KeyError):
                    continue
        return count
    except (OSError, TelegramAlertError):
        return 0



# Duplicate render guard is embedded because the pinned Windows updater may
# only update allowlisted files; helper modules cannot be installed remotely.
import struct
import zlib

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_PNG = 8_000_000
_MAX_SCANLINES = 48_000_000
_MAX_SEARCH = 24


def _png_scanlines(path: Path) -> tuple[tuple[int, ...], bytes] | None:
    """Return reconstructed pixel bytes (without metadata or PNG filters).

    Identical Blender frames may have different file metadata. Comparing IDAT
    content rather than whole-file bytes prevents that metadata defeating dedup.
    Invalid, oversized, or unsafe image files are never decompressed.
    """
    try:
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            return None
        size = path.stat().st_size
        if not 64 <= size <= _MAX_PNG:
            return None
        data = path.read_bytes()
        if not data.startswith(_PNG_SIGNATURE):
            return None
        offset = len(_PNG_SIGNATURE)
        dimensions = None
        chunks = []
        total_idat = 0
        for _ in range(256):
            if offset + 12 > len(data):
                return None
            length = struct.unpack_from(">I", data, offset)[0]
            name = data[offset + 4:offset + 8]
            end = offset + 12 + length
            if length > _MAX_PNG or end > len(data):
                return None
            payload = data[offset + 8:offset + 8 + length]
            offset = end
            if name == b"IHDR":
                if dimensions is not None or length != 13:
                    return None
                width, height, depth, color, comp, fltr, interlace = struct.unpack(">IIBBBBB", payload)
                if not (1 <= width <= 4096 and 1 <= height <= 4096):
                    return None
                if depth not in (8, 16) or color not in (0, 2, 4, 6) or comp or fltr or interlace:
                    return None
                channels = {0: 1, 2: 3, 4: 2, 6: 4}[color]
                uncompressed_size = height * (1 + width * channels * (depth // 8))
                if uncompressed_size > _MAX_SCANLINES:
                    return None
                dimensions = (width, height, depth, color)
            if name == b"IDAT":
                total_idat += length
                if total_idat > _MAX_PNG:
                    return None
                chunks.append(payload)
            if name == b"IEND":
                break
        if dimensions is None or not chunks:
            return None
        stream = zlib.decompressobj()
        image = stream.decompress(b"".join(chunks), _MAX_SCANLINES + 1)
        if stream.unconsumed_tail or not stream.eof:
            return None
        if len(image) != uncompressed_size:
            return None
        # PNG filters encode differences, not pixel values. Undo each row before
        # comparing: the same pixels can use different encoder/filter choices.
        stride = width * channels * (depth // 8)
        bpp = channels * (depth // 8)
        pixels = bytearray(height * stride)
        previous = bytearray(stride)
        for row in range(height):
            start = row * (stride + 1)
            kind = image[start]
            if kind > 4:
                return None
            current = bytearray(image[start + 1:start + 1 + stride])
            for i in range(stride):
                left = current[i - bpp] if i >= bpp else 0
                up = previous[i]
                diagonal = previous[i - bpp] if i >= bpp else 0
                if kind == 1:
                    predictor = left
                elif kind == 2:
                    predictor = up
                elif kind == 3:
                    predictor = (left + up) // 2
                elif kind == 4:
                    estimate = left + up - diagonal
                    da, db, dc = abs(estimate-left), abs(estimate-up), abs(estimate-diagonal)
                    predictor = left if da <= db and da <= dc else up if db <= dc else diagonal
                else:
                    predictor = 0
                current[i] = (current[i] + predictor) & 255
            pixels[row * stride:(row + 1) * stride] = current
            previous = current
        return dimensions, bytes(pixels)
    except (OSError, ValueError, struct.error, zlib.error, OverflowError):
        return None


def front_difference(first: Path, second: Path) -> dict[str, object] | None:
    """Normalized difference of bounded reconstructed pixel samples.

    The metric is deliberately conservative: it is only a repeated-render
    warning, not a perceptual similarity/identity approval.
    """
    a = _png_scanlines(first)
    b = _png_scanlines(second)
    if a is None or b is None or a[0] != b[0] or len(a[1]) != len(b[1]):
        return None
    if hashlib.sha256(a[1]).digest() == hashlib.sha256(b[1]).digest():
        return {"duplicate": True, "average_abs_byte_delta": 0.0,
                "reason": "identical_decoded_png"}
    step = max(1, len(a[1]) // 65_536)
    aa = a[1][::step]
    bb = b[1][::step]
    difference = sum(abs(x - y) for x, y in zip(aa, bb)) / len(aa)
    return {"duplicate": difference <= 0.8,
            "average_abs_byte_delta": round(difference, 4),
            "reason": "near_identical_png" if difference <= 0.8 else "different_png"}


def find_recent_duplicate(project: Path, review: Path) -> dict[str, object] | None:
    """Compare front with recent separate review jobs; never follow symlinks."""
    current = review / "front.png"
    if _png_scanlines(current) is None:
        return None
    try:
        previous = [
            p for p in project.iterdir()
            if p != review and p.is_dir() and not p.is_symlink()
            and not getattr(p, "is_junction", lambda: False)()
            and (p / "front.png").is_file()
            and (p / "front.png").stat().st_mtime <= current.stat().st_mtime
        ]
        previous.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for old in previous[:_MAX_SEARCH]:
            value = front_difference(current, old / "front.png")
            if value is not None and value["duplicate"]:
                return {"matched_review": old.name, **value}
    except OSError:
        return None
    return None



def telegram_send_mia_review_photos(workspace: str | Path, task_id: str) -> dict:
    """Best-effort delivery of fixed, previously rendered PNG stills.

    The filenames, target bot/chat and root path are fixed. A remote mailbox
    request never supplies paths, URLs, recipients or media bytes.
    Direct Telegram multipart upload is used; the optional JSON-only Render
    relay cannot forward multipart images. All originals remain local.
    """
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", task_id):
        return {"status": "blocked", "reason": "invalid_review_id"}
    try:
        token, chat = _telegram_credentials()
        if not token or not chat:
            return {"status": "not_configured"}
        if not telegram_notifications_enabled():
            return {"status": "disabled_in_local_studio"}
        import requests
        base = Path(workspace).expanduser().resolve()
        project = base / "MIA_REFERENCE_REVIEW"
        review = project / task_id
        for entry in (project, review):
            if (entry.is_symlink() or getattr(entry, "is_junction", lambda: False)()):
                return {"status": "blocked", "reason": "unsafe_review_directory"}
        if not review.is_dir() or not review.resolve().is_relative_to(base):
            return {"status": "blocked", "reason": "review_directory_missing"}
        # A repeated task ID or nearly unchanged rendered image must not spam Telegram.
        marker = review / ".telegram_delivery.json"
        if marker.is_symlink() or getattr(marker, "is_junction", lambda: False)():
            return {"status": "blocked", "reason": "unsafe_telegram_marker"}
        views = ("front", "three_quarter", "side", "back")
        previous_sent = []
        if marker.exists():
            if not marker.is_file() or marker.stat().st_size > 4096:
                return {"status": "blocked", "reason": "invalid_delivery_receipt"}
            try:
                receipt = json.loads(marker.read_text("utf-8"))
                if (not isinstance(receipt, dict) or receipt.get("task_id") != task_id
                        or not isinstance(receipt.get("views_sent"), list)
                        or any(v not in views for v in receipt["views_sent"])):
                    return {"status": "blocked", "reason": "invalid_delivery_receipt"}
                previous_sent = list(dict.fromkeys(receipt["views_sent"]))
            except (OSError, ValueError, TypeError):
                return {"status": "blocked", "reason": "invalid_delivery_receipt"}
            if len(previous_sent) == len(views):
                return {"status": "already_delivered", "sent": [], "failed": []}
        duplicate = None if previous_sent else find_recent_duplicate(project, review)
        if duplicate:
            return {"status": "suppressed_duplicate",
                    "reason": "unchanged_mia_front_render",
                    "duplicate_of": duplicate["matched_review"],
                    "render_delta": duplicate["average_abs_byte_delta"],
                    "identity_verified": False, "sent": [], "failed": []}
        url = "https://api.telegram.org/bot" + token + "/sendPhoto"
        sent = []
        failed = []
        for view in views:
            if view in previous_sent:
                continue
            file = review / (view + ".png")
            if (file.is_symlink() or getattr(file, "is_junction", lambda: False)()
                    or not file.is_file() or not 64 <= file.stat().st_size <= 8_000_000):
                failed.append(view)
                continue
            # Validate PNG signature and avoid accidental unrelated files.
            with file.open("rb") as stream:
                if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                    failed.append(view)
                    continue
                stream.seek(0)
                try:
                    response = requests.post(
                        url,
                        data={"chat_id": chat, "caption": "Мия: черновая 3D-модель • " + view
                              + " • требуется проверка внешности; не анимация"},
                        files={"photo": (view + ".png", stream, "image/png")},
                        timeout=(8, 30), allow_redirects=False)
                    valid = (response.status_code == 200
                             and response.headers.get("Content-Type", "").startswith("application/json")
                             and response.json().get("ok") is True)
                except (requests.RequestException, ValueError, TypeError):
                    valid = False
            if valid:
                sent.append(view)
            else:
                failed.append(view)
        delivered_views = list(dict.fromkeys(previous_sent + sent))
        if sent:
            # Store only a local delivery receipt, never credentials or media.
            try:
                tmp = review / ".telegram_delivery.tmp"
                if tmp.is_symlink() or getattr(tmp, "is_junction", lambda: False)():
                    return {"status": "partial", "sent": sent, "failed": failed,
                            "reason": "unsafe_delivery_marker"}
                tmp.write_text(json.dumps({"task_id": task_id,
                    "views_sent": delivered_views, "identity_verified": False}, sort_keys=True),
                    encoding="utf-8")
                tmp.replace(marker)
            except OSError:
                return {"status": "partial", "sent": sent, "failed": failed,
                        "reason": "delivery_marker_write_failed"}
        return {"status": "delivered" if len(delivered_views) == 4 else
                "partial" if delivered_views else "failed", "sent": sent,
                "previously_sent": previous_sent, "failed": failed,
                "transport": "direct_telegram_multipart",
                "note": "The configured text relay does not yet support photo attachments."
                        if telegram_transport_settings()["use_relay"] and failed else ""}
    except (OSError, RuntimeError, ValueError, TelegramAlertError):
        return {"status": "failed", "reason": "telegram_photo_delivery_unavailable"}


def telegram_send_test(data: dict) -> dict:
    if data != {}:
        raise TelegramAlertError("Лишние параметры запроса")
    if not telegram_notifications_enabled():
        raise TelegramAlertError("Уведомления Telegram выключены в настройках")
    token, chat = _telegram_credentials()
    if not token or not chat:
        raise TelegramAlertError("Сначала привяжите Telegram-чат")
    _telegram_call(token, "sendMessage",
                   {"chat_id": chat, "text": "Проверка связи: Blender AI Agent на Windows работает."})
    return {"sent": True}




class ReviewStudioJobs(StudioJobs):
    """Export complete Blender renders to a locally authorized Dropbox folder."""

    def _publish_visual_review(self, job_id: str, directory: Path, ffmpeg: str) -> None:
        try:
            info = self.status(job_id)
            if info.get("state") != "completed":
                return
            result = export_review(directory, info, ffmpeg)
        except (ReviewDeliveryError, OSError, ValueError) as exc:
            result = {"status": "failed", "reason": str(exc)[:180]}
        except Exception as exc:
            result = {"status": "failed", "error_type": type(exc).__name__}
        if result.get("status") == "exported_to_local_dropbox":
            telegram_queue_event("studio:" + job_id,
                                 "Blender Studio: видео готово. Кадры отправлены в Dropbox. Задача " + job_id[:12])
            telegram_flush_outbox(max_messages=2)
        elif result.get("status") == "failed":
            telegram_queue_event("studio-export-error:" + job_id,
                                 "Blender Studio: ошибка отправки в Dropbox. Проверьте Studio.")
            telegram_flush_outbox(max_messages=2)
        if result.get("status") == "disabled":
            return
        try:
            with self.lock:
                info = self.status(job_id)
                if info.get("state") == "completed":
                    info["review_delivery"] = result
                    self._write(directory, info)
        except (OSError, ValueError):
            pass

    def _run(self, job_id: str, d: Path, blender: str, ffmpeg: str):
        super()._run(job_id, d, blender, ffmpeg)
        self._publish_visual_review(job_id, d, ffmpeg)

    def _assemble(self, info: dict, video_paths: list[Path], ffmpeg: str):
        super()._assemble(info, video_paths, ffmpeg)
        self._publish_visual_review(info["job_id"], self._path(info["job_id"]), ffmpeg)


class StudioHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store: StudioStore):
        super().__init__(address, StudioHandler)
        self.store = store
        self.jobs = ReviewStudioJobs(store)
        self.render_lock = threading.Lock()
        self.octava_lock = threading.Lock()
        self.mailbox_policy_lock = threading.Lock()
        self.render_status = {"state": "idle", "message": "Рендер ещё не запускался."}

    def start_demo(self, source: str, lens: float) -> dict:
        """Explicit fixed-timeline Blender smoke-test, NOT prompt-driven rendering."""
        from local_agent.blender_locator import find_blender_executable
        try:
            candidate = Path(source).expanduser()
            if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
                raise StudioError("Символические ссылки запрещены")
            actual = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise StudioError("Указанный .blend файл не найден") from exc
        if not actual.is_relative_to(self.store.workspace) or actual.suffix.lower() != ".blend" or not actual.is_file():
            raise StudioError("Выберите .blend в локальной рабочей папке")
        if isinstance(lens, bool) or not isinstance(lens, (int, float)) or not 18 <= lens <= 100:
            raise StudioError("Фокусное расстояние должно быть 18–100 мм")
        executable = find_blender_executable()
        if executable is None:
            raise StudioError("Blender не найден")
        with self.render_lock:
            if self.render_status["state"] == "running":
                raise StudioConflict("Рендер уже выполняется")
            output = self.store.root / "renders" / ("demo_" + uuid.uuid4().hex[:12])
            output.parent.mkdir(parents=True, exist_ok=True)
            log = output.parent / (output.name + ".log")
            self.render_status = {"state": "running", "message": "Технический тест Blender запущен", "output": str(output), "log": str(log)}
        def worker():
            try:
                command = [sys.executable, "-m", "local_agent.multiscene_cli", "--source", str(actual),
                           "--output", str(output), "--camera-lens-mm", str(lens), "--blender", str(executable)]
                with log.open("w", encoding="utf-8", errors="replace") as stream:
                    result = subprocess.run(command, cwd=str(Path(__file__).resolve().parent.parent),
                                            stdout=stream, stderr=subprocess.STDOUT,
                                            timeout=2400, check=False, shell=False)
                status = ("completed" if result.returncode == 0 and (output / "multiscene.mp4").is_file() else "failed")
                message = "Тестовый MP4 готов" if status == "completed" else f"Рендер завершился с кодом {result.returncode}; проверьте лог"
            except (OSError, subprocess.TimeoutExpired) as exc:
                status, message = "failed", f"{type(exc).__name__}: {exc}"
            with self.render_lock:
                self.render_status = {"state": status, "message": message, "output": str(output), "log": str(log)}
        threading.Thread(target=worker, daemon=True).start()
        return dict(self.render_status)


def astra_monitor_snapshot(root: Path | None = None) -> dict:
    """Expose only bounded audit checkpoints, never arbitrary local files."""
    root = root or Path(__file__).resolve().parents[1]/'.local_agent'/'reports'
    result = {'tasks': [], 'observed_at': datetime.now(timezone.utc).isoformat(),
              'notice': 'Сохранённый обмен. Отсутствие новых записей не доказывает остановку процесса.'}
    def safe(path):
        return not path.is_symlink() and not getattr(path,'is_junction',lambda:False)()
    def clean(text):
        text = re.sub(r'(?i)(gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|\b\d{7,12}:[A-Za-z0-9_-]{30,})','[REDACTED]',text)
        text = re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9_.-]{15,}',r'\1[REDACTED]',text)
        return re.sub(r'(?im)([\"\']?(?:api[_-]?key|token|password|secret)[\"\']?\s*[=:]\s*)[\"\'][^\"\'\n]{8,}[\"\']',r'\1"[REDACTED]"',text)
    if not safe(root) or not root.is_dir():
        return result
    try:
        folders = [p for p in root.iterdir() if safe(p) and p.is_dir() and re.fullmatch(r'astra[A-Za-z0-9._-]{0,120}',p.name)]
        folders.sort(key=lambda p:p.stat().st_mtime,reverse=True)
        for folder in folders[:8]:
            task = {'task_id':folder.name, 'events':[], 'progress':{}}
            progress = folder/'progress.json'
            if safe(progress) and progress.is_file() and progress.stat().st_size<=64000:
                try:
                    data=json.loads(progress.read_text(encoding='utf-8'))
                    task['progress']={k:data[k] for k in ('source_chunks','chunks_sent','files_in_archive') if type(data.get(k)) is int}
                except (OSError,ValueError,UnicodeError,TypeError):
                    task['progress_unreadable']=True
            files=[p for p in folder.iterdir() if safe(p) and p.is_file() and re.fullmatch(r'(?:PROMPT\.txt|AUDIT_REPORT\.md|WORK_PROMPT\.txt|(?:request_)?(?:part|synthesis)_\d+\.txt)',p.name)]
            files.sort(key=lambda p:p.stat().st_mtime,reverse=True)
            for path in files[:12]:
                if path.stat().st_size>500000:
                    continue
                with path.open('r',encoding='utf-8',errors='replace') as stream:
                    text=stream.read(10001)
                kind='request' if path.name.startswith('request_') or path.name=='PROMPT.txt' else 'response'
                task['events'].append({'file':path.name,'kind':kind,'time':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),'text':clean(text[:10000]),'truncated':len(text)>10000})
            task['final_report_saved']=(folder/'AUDIT_REPORT.md').is_file() and safe(folder/'AUDIT_REPORT.md')
            result['tasks'].append(task)
    except OSError:
        result['read_error']=True
    return result


class StudioHandler(BaseHTTPRequestHandler):
    server: StudioHTTPServer

    def log_message(self, format, *args):
        # Only local requests; avoid logging request bodies or user-authored text.
        if os.environ.get("STUDIO_HTTP_DEBUG") == "1":
            super().log_message(format, *args)

    def _headers(self, code: int, mime: str, length: int):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; media-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()

    def _send(self, code: int, body: bytes, mime="application/json; charset=utf-8"):
        self._headers(code, mime, len(body))
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _request_allowed(self) -> bool:
        expected = f"127.0.0.1:{self.server.server_port}"
        return self.headers.get("Host") in (expected, f"localhost:{self.server.server_port}")

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        return not origin or origin in (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}")

    def do_GET(self):
        if not self._request_allowed():
            self._json(403, {"error": "Host rejected"})
            return
        path = urlsplit(self.path).path
        if path == "/api/astra-monitor":
            return self._json(200, astra_monitor_snapshot())
        if path == "/api/health":
            return self._json(200, {"status": "ok", "offline": True})
        if path == "/api/octava-key":
            try:
                return self._json(200, key_status())
            except OctavaKeyError as exc:
                return self._json(503, {"error": str(exc)})
        if path == "/api/mailbox-policy":
            try:
                return self._json(200, load_policy())
            except MailboxPolicyError as exc:
                return self._json(503, {"error": str(exc)})
        if path == "/api/trusted-updates":
            try:
                return self._json(200, get_opt_in())
            except MailboxPolicyError as exc:
                return self._json(503, {"error": str(exc)})
        if path == "/api/dropbox-review":
            try:
                return self._json(200, review_status())
            except ReviewDeliveryError as exc:
                return self._json(503, {"error": str(exc)})
        if path == "/api/telegram-status":
            try:
                return self._json(200, telegram_status())
            except TelegramAlertError as exc:
                return self._json(503, {"error": str(exc)})
        if path == "/api/telegram-notifications":
            try:
                return self._json(200, {"notifications_enabled": load_telegram_notifications()["enabled"]})
            except MailboxPolicyError as exc:
                return self._json(503, {"error": str(exc)})
        if path == "/api/agent-runtime":
            try:
                current = load_runtime_control()
                return self._json(200, {"paused": current["paused"],
                                        "restart_pending": current["restart_requested"] != current["restart_acknowledged"]})
            except MailboxPolicyError as exc:
                return self._json(503, {"error": str(exc)})
        if path == "/api/telegram-transport":
            try:
                return self._json(200, telegram_transport_settings())
            except TelegramAlertError as exc:
                return self._json(503, {"error": str(exc)})
        if path == "/api/approved-references":
            return self._json(200, {"references": [approved_status(self.server.store.workspace)]})
        if path == "/api/approved-reference-image/mia":
            try:
                raw = approved_bytes(self.server.store.workspace)
            except (StudioError, OSError):
                raw = None
            if raw is None:
                return self._json(404, {"error": "Approved reference unavailable or invalid"})
            return self._send(200, raw, "image/jpeg")
        if path == "/api/asset-library":
            return self._json(200, list_season_asset_library(self.server.store))
        if path.startswith("/api/asset-image/"):
            asset_id = path.removeprefix("/api/asset-image/")
            result = _asset_reference_image(self.server.store, asset_id)
            if result is None:
                return self._json(404, {"error": "Visual reference is not registered locally"})
            raw, mime = result
            return self._send(200, raw, mime)
        if path == "/api/state":
            try:
                return self._json(200, self.server.store.load())
            except StudioError as exc:
                return self._json(500, {"error": str(exc)})
        if path == "/api/episodes":
            result = list_season_episodes()
            for episode in result["episodes"]:
                episode.update(_episode_asset_readiness(episode, self.server.store))
            return self._json(200, result)
        if path.startswith("/api/episodes/"):
            suffix = path.removeprefix("/api/episodes/")
            if suffix.endswith("/history"):
                episode_id = suffix.removesuffix("/history").rstrip("/")
                try:
                    return self._json(200, {"episode_id": episode_id, "revisions": get_season_episode_history(episode_id)})
                except StudioError as exc:
                    return self._json(404, {"error": str(exc)})
            try:
                episode = get_season_episode(suffix)
                episode.update(_episode_asset_readiness(episode, self.server.store))
                return self._json(200, episode)
            except StudioError as exc:
                return self._json(404, {"error": str(exc)})
        if path == "/api/studio-latest":
            return self._json(200, {"job": self.server.jobs.latest()})
        if path == "/api/agent-task":
            try:
                from local_agent.studio_jobs import agent_task_status
                return self._json(200, agent_task_status())
            except StudioJobError as exc:
                return self._json(500, {"error": str(exc)})
        if path.startswith("/api/studio-job/"):
            try:
                return self._json(200, self.server.jobs.status(path.removeprefix("/api/studio-job/")))
            except StudioJobError as exc:
                return self._json(404, {"error": str(exc)})
        if path.startswith("/api/studio-video/"):
            try:
                video = self.server.jobs.video(path.removeprefix("/api/studio-video/"))
                size = video.stat().st_size
                range_header = self.headers.get("Range", "")
                start, end = 0, size - 1
                if range_header:
                    matched = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header)
                    if not matched:
                        return self._json(416, {"error": "Invalid range"})
                    start = int(matched.group(1))
                    end = int(matched.group(2)) if matched.group(2) else size - 1
                    if start >= size or end >= size or end < start:
                        return self._json(416, {"error": "Out of range"})
                self.send_response(206 if range_header else 200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}") if range_header else None
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                with video.open("rb") as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining > 0:
                        chunk = stream.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return
            except StudioJobError as exc:
                return self._json(404, {"error": str(exc)})
        if path == "/api/render-status":
            with self.server.render_lock:
                return self._json(200, dict(self.server.render_status))
        if path == "/api/preview.mp4":
            with self.server.render_lock:
                report = dict(self.server.render_status)
            if report.get("state") != "completed":
                return self._json(404, {"error": "No video available"})
            video = Path(report["output"]) / "multiscene.mp4"
            if (not video.is_file() or video.is_symlink()
                    or not video.resolve().is_relative_to(self.server.store.root)
                    or video.stat().st_size > 100_000_000):
                return self._json(404, {"error": "Video not found"})
            return self._send(200, video.read_bytes(), "video/mp4")
        if path.startswith("/media/"):
            filename = path.removeprefix("/media/")
            if not _MEDIA_NAME.fullmatch(filename):
                return self._json(404, {"error": "Image not found"})
            target = self.server.store.root / "studio_media" / filename
            if target.is_symlink() or not target.is_file():
                return self._json(404, {"error": "Image not found"})
            return self._send(200, target.read_bytes(), _IMAGE_MIMES[target.suffix[1:]])
        static = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8"),
                  "/app.js": ("app.js", "application/javascript; charset=utf-8")}.get(path)
        if not static:
            return self._json(404, {"error": "Not found"})
        return self._send(200, (_STATIC / static[0]).read_bytes(), static[1])

    def do_POST(self):
        if not self._request_allowed() or not self._same_origin():
            return self._json(403, {"error": "Cross-origin request rejected"})
        path = urlsplit(self.path).path
        if path in ("/api/octava-key", "/api/octava-model", "/api/link-mia-reference", "/api/mailbox-policy", "/api/trusted-updates", "/api/dropbox-review", "/api/telegram-configure", "/api/telegram-pair", "/api/telegram-test", "/api/telegram-transport", "/api/telegram-notifications", "/api/agent-pause", "/api/agent-restart") and self.headers.get("Origin") not in (
                f"http://127.0.0.1:{self.server.server_port}",
                f"http://localhost:{self.server.server_port}"):
            return self._json(403, {"error": "Local studio origin required"})
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return self._json(415, {"error": "Expected application/json"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= _MAX_REQUEST or (path == "/api/octava-key" and length > 2700) or (path == "/api/octava-model" and length > 240) or (path == "/api/link-mia-reference" and length > 128) or (path == "/api/mailbox-policy" and length > 300) or (path == "/api/trusted-updates" and length > 100) or (path == "/api/dropbox-review" and length > 100) or (path in ("/api/telegram-configure", "/api/telegram-pair", "/api/telegram-test", "/api/telegram-transport", "/api/telegram-notifications", "/api/agent-pause", "/api/agent-restart") and length > 240):
            return self._json(413, {"error": "Invalid request size"})
        try:
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise StudioError("JSON object required")
            if path == "/api/octava-key":
                if set(body) != {"api_key"}:
                    raise StudioError("Укажите только новый API-ключ")
                with self.server.octava_lock:
                    result = replace_key(body["api_key"])
                return self._json(200, result)
            if path == "/api/octava-model":
                with self.server.octava_lock:
                    return self._json(200, set_default_model(body))
            if path == "/api/mailbox-policy":
                with self.server.mailbox_policy_lock:
                    return self._json(200, save_policy(body))
            if path == "/api/trusted-updates":
                with self.server.mailbox_policy_lock:
                    return self._json(200, set_opt_in(body))
            if path == "/api/dropbox-review":
                with self.server.mailbox_policy_lock:
                    return self._json(200, save_settings(body))
            if path == "/api/agent-pause":
                if set(body) != {"paused"} or type(body.get("paused")) is not bool:
                    raise StudioError("Ожидается только поле paused: true/false")
                with self.server.mailbox_policy_lock:
                    result = set_runtime_pause(body)
                return self._json(200, {"paused": result["paused"]})
            if path == "/api/agent-restart":
                with self.server.mailbox_policy_lock:
                    return self._json(202, request_runtime_restart(body))
            if path == "/api/telegram-notifications":
                with self.server.mailbox_policy_lock:
                    return self._json(200, telegram_set_notifications(body))
            if path == "/api/telegram-transport":
                with self.server.mailbox_policy_lock:
                    return self._json(200, telegram_set_transport(body))
            if path == "/api/telegram-configure":
                with self.server.mailbox_policy_lock:
                    return self._json(200, telegram_save_token(body))
            if path == "/api/telegram-pair":
                with self.server.mailbox_policy_lock:
                    return self._json(200, telegram_pair_chat(body))
            if path == "/api/telegram-test":
                return self._json(200, telegram_send_test(body))
            if path == "/api/link-mia-reference":
                if set(body) != {"revision"}:
                    raise StudioError("Only project revision is allowed")
                return self._json(200, attach_approved_mia(self.server.store, body["revision"]))
            if path == "/api/episodes/import":
                if set(body) != {"filename", "content_base64"}:
                    raise StudioError("Ожидаются только имя TXT-файла и его данные.")
                encoded = body.get("content_base64")
                if not isinstance(encoded, str) or len(encoded) > 1_400_000:
                    raise StudioError("Некорректный или слишком большой файл сценария.")
                raw = base64.b64decode(encoded, validate=True)
                result = import_season_screenplay(body.get("filename"), raw)
                result["season"] = list_season_episodes()
                return self._json(201 if not result["already_imported"] else 200, result)
            if path == "/api/episodes/edit":
                if set(body) != {"episode_id", "revision", "text"}:
                    raise StudioError("Ожидаются ID серии, ревизия и полный текст серии.")
                episode = edit_season_episode(body["episode_id"], body["revision"], body["text"])
                episode.update(_episode_asset_readiness(episode, self.server.store))
                return self._json(200, episode)
            if path == "/api/state":
                result = self.server.store.save(body.get("state"), body.get("revision"))
                return self._json(200, result)
            if path == "/api/interpret":
                state = self.server.store.load()
                if body.get("revision") != state["revision"]:
                    raise StudioConflict("Save edits before interpreting")
                scene_id = body.get("scene_id")
                scene = next((x for x in state["scenes"] if x["id"] == scene_id), None)
                if scene is None:
                    raise StudioError("Scene not found")
                context = dict(state)
                context["settings"] = {**state["settings"], "duration": scene["duration"]}
                return self._json(200, interpret_scene(scene["prompt"], context, scene_id))
            if path == "/api/render-scene":
                state = self.server.store.load()
                if body.get("revision") != state["revision"]:
                    raise StudioConflict("Save edits before rendering")
                return self._json(202, self.server.jobs.start(state, body.get("scene_id")))
            if path == "/api/render-project":
                state = self.server.store.load()
                if body.get("revision") != state["revision"]:
                    raise StudioConflict("Save edits before project assembly")
                return self._json(202, self.server.jobs.compose(state))
            if path == "/api/cancel-scene":
                return self._json(200, self.server.jobs.cancel(body.get("job_id")))
            if path == "/api/cancel-agent-task":
                if set(body) != {"task_id"}:
                    raise StudioError("Expected only task_id")
                from local_agent.studio_jobs import request_agent_task_cancel
                return self._json(200, request_agent_task_cancel(body.get("task_id")))
            if path == "/api/prepare":
                state = self.server.store.load()
                if body.get("revision") != state["revision"]:
                    raise StudioConflict("State changed; save before preparing")
                plan = to_story_plan(state)
                outcome = save_story_plan(self.server.store.workspace, plan)
                compiled = compile_story_plan(plan)
                return self._json(200, {"result": outcome, "readiness": compiled["readiness"], "requirements": compiled.get("requirements_not_implemented", [])})
            if path == "/api/image":
                return self._json(201, self._save_image(body))
            if path == "/api/demo-render":
                return self._json(202, self.server.start_demo(body.get("source", ""), body.get("lens", 42)))
            return self._json(404, {"error": "Unknown endpoint"})
        except StudioConflict as exc:
            return self._json(409, {"error": str(exc)})
        except (StudioError, StudioJobError, PromptError, StoryPlanError, OctavaKeyError, MailboxPolicyError, ReviewDeliveryError, TelegramAlertError, ValueError, TypeError, binascii.Error) as exc:
            return self._json(400, {"error": str(exc)})
        except OSError as exc:
            return self._json(500, {"error": f"Local file error: {type(exc).__name__}"})

    def _save_image(self, body: dict) -> dict:
        extension = body.get("extension")
        if extension not in _IMAGE_MIMES:
            raise StudioError("Only PNG, JPG and WEBP images are supported")
        data = body.get("data")
        if not isinstance(data, str) or len(data) > 4_500_000:
            raise StudioError("Image is missing or too large")
        raw = base64.b64decode(data, validate=True)
        if not 0 < len(raw) <= 3_000_000:
            raise StudioError("Image size must not exceed 3 MB")
        signatures = {"png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
                      "jpg": raw.startswith(b"\xff\xd8\xff"),
                      "webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"}
        if not signatures[extension]:
            raise StudioError("Image type does not match its content")
        folder = self.server.store.root / "studio_media"
        if folder.is_symlink() or getattr(folder, "is_junction", lambda: False)():
            raise StudioError("Unsafe media folder")
        folder.mkdir(exist_ok=True)
        filename = uuid.uuid4().hex + "." + extension
        with (folder / filename).open("xb") as stream:
            stream.write(raw)
        return {"filename": filename, "url": "/media/" + filename}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local-only Blender AI Agent studio")
    parser.add_argument("--workspace", default=os.environ.get("LOCAL_AGENT_WORKSPACE", str(Path.home() / "BlenderAgentWorkspace")))
    parser.add_argument("--project", default="mia_story")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("Invalid port")
    store = StudioStore(args.workspace, args.project)
    server = StudioHTTPServer(("127.0.0.1", args.port), store)
    url = f"http://127.0.0.1:{server.server_port}/"
    print("Blender AI Agent studio:", url, flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

