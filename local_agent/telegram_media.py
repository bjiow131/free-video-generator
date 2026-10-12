"""Read-only, allowlisted Studio assets for private Telegram media replies.

Remote commands never supply filenames. No arbitrary filesystem paths, shell commands,
cloud object storage, or user-defined destinations are accepted here.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_JOB_ID = re.compile(r"[a-f0-9]{32}\Z")
_MEDIA_ID = re.compile(r"[a-f0-9]{32}\.(?:png|jpg|webp)\Z")
_FRAME_ID = re.compile(r"frame_[0-9]{4,6}\.png\Z")
_MAX_STATUS = 16_384
_MAX_IMAGE = 9_500_000
_MAX_VIDEO = 32_000_000


class TelegramMediaError(ValueError):
    pass


def _project() -> Path:
    workspace = Path(os.environ.get(
        "LOCAL_AGENT_WORKSPACE", str(Path.home() / "BlenderAgentWorkspace")
    )).expanduser()
    project = workspace / "mia_story"
    if project.is_symlink() or getattr(project, "is_junction", lambda: False)():
        raise TelegramMediaError("Недопустимая папка Studio")
    if not project.is_dir():
        raise TelegramMediaError("Локальный проект Studio ещё не создан")
    return project


def _safe_file(project: Path, relative: Path, limit: int) -> Path:
    """Reject links/junctions in every component and paths outside the project."""
    if relative.is_absolute() or any(part in ("..", "") for part in relative.parts):
        raise TelegramMediaError("Недопустимый путь к изображению")
    current = project
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise TelegramMediaError("Ссылки в медиафайлах запрещены")
    try:
        if not current.is_file() or not current.resolve(strict=True).is_relative_to(project.resolve(strict=True)):
            raise TelegramMediaError("Медиафайл не найден")
        size = current.stat().st_size
    except (OSError, RuntimeError) as exc:
        raise TelegramMediaError("Медиафайл недоступен") from exc
    if size < 16 or size > limit:
        raise TelegramMediaError("Размер файла превышает допустимый для Telegram")
    return current


def _json_file(project: Path, relative: Path, max_bytes: int) -> dict:
    file = _safe_file(project, relative, max_bytes)
    try:
        result = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise TelegramMediaError("Не удалось прочитать состояние Studio") from exc
    if not isinstance(result, dict):
        raise TelegramMediaError("Некорректное состояние Studio")
    return result


def _latest_job(project: Path, kind: str) -> tuple[str, dict]:
    jobs = project / "studio_jobs"
    if jobs.is_symlink() or getattr(jobs, "is_junction", lambda: False)() or not jobs.is_dir():
        raise TelegramMediaError("Готовых сцен пока нет")
    choices: list[tuple[float, str, dict]] = []
    for child in jobs.iterdir():
        if (len(choices) >= 1000 or not _JOB_ID.fullmatch(child.name)
                or child.is_symlink() or not child.is_dir()):
            continue
        try:
            info = _json_file(project, Path("studio_jobs") / child.name / "job.json", _MAX_STATUS)
            stamp = info.get("created_at")
            if (info.get("job_id") != child.name or info.get("state") != "completed"
                    or type(stamp) not in (int, float) or not 0 <= stamp <= 1e12):
                continue
            if kind == "preview" and info.get("kind", "scene") != "scene":
                continue
            choices.append((float(stamp), child.name, info))
        except TelegramMediaError:
            continue
    if not choices:
        raise TelegramMediaError("Готовых сцен для отправки ещё нет")
    _, job_id, info = max(choices, key=lambda item: (item[0], item[1]))
    return job_id, info


def media_for_job(project: Path, job_id: str, kind: str, info: dict) -> tuple[Path, str, str]:
    """Resolve an already completed render to a photo or MP4 without a caller path."""
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise TelegramMediaError("Некорректный ID рендера")
    if info.get("job_id") != job_id or info.get("state") != "completed":
        raise TelegramMediaError("Рендер ещё не завершён")
    base = Path("studio_jobs") / job_id
    label = str(info.get("scene_id", "сцена"))[:48]
    if kind == "video":
        file = _safe_file(project, base / "scene.mp4", _MAX_VIDEO)
        return file, "sendVideo", "Blender: готовое видео · " + label + " · " + job_id[:8]
    if kind == "preview":
        if info.get("kind", "scene") != "scene":
            raise TelegramMediaError("Для монтажа последний кадр не сохранён")
        frames = project / base / "frames"
        if frames.is_symlink() or getattr(frames, "is_junction", lambda: False)() or not frames.is_dir():
            raise TelegramMediaError("Кадры сцены не найдены")
        # Use the exact final rendered frame (not a newly generated approximation).
        total = info.get("total_frames")
        if type(total) is not int or not 1 <= total <= 999999:
            raise TelegramMediaError("Неизвестен номер последнего кадра")
        file = _safe_file(project, base / "frames" / f"frame_{total:04d}.png", _MAX_IMAGE)
        return file, "sendPhoto", "Blender: последний кадр · " + label + " · " + job_id[:8]
    raise TelegramMediaError("Неизвестный тип медиа")


def resolve_media(kind: str) -> tuple[Path, str, str]:
    project = _project()
    if kind in ("preview", "video"):
        job_id, info = _latest_job(project, kind)
        return media_for_job(project, job_id, kind, info)
    if kind == "reference":
        state = _json_file(project, Path("studio_state.json"), 256_000)
        characters = state.get("characters")
        if not isinstance(characters, list):
            raise TelegramMediaError("Библиотека персонажей недоступна")
        mia = next((c for c in characters if isinstance(c, dict) and c.get("id") == "mia"), None)
        ref = mia.get("reference") if mia else None
        if not isinstance(ref, str) or not _MEDIA_ID.fullmatch(ref):
            raise TelegramMediaError("В карточке Мии пока нет загруженного референса")
        file = _safe_file(project, Path("studio_media") / ref, _MAX_IMAGE)
        return file, "sendPhoto", "Мия · референс из локальной карточки персонажа"
    raise TelegramMediaError("Неизвестная команда медиа")
