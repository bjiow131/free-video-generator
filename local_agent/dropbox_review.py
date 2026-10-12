"""Opt-in local Dropbox sync folder for Blender visual QA.

No Dropbox API key is required: the Windows Dropbox desktop application
syncs files placed in the account's local folder. A scene is exported only
after an explicit opt-in stored on the Windows computer.
"""
from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / ".local_agent" / "dropbox_review.json"
REVIEW_FOLDER = "AI-Agent-Reviews"
MAX_VIDEO_BYTES = 32_000_000
MAX_REVIEW_JOBS = 40
_JOB_RE = re.compile(r"[a-f0-9]{32}\Z")
_LOCK = threading.RLock()


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
    """Recognize account folders reported by Dropbox Desktop or explicit local override."""
    override = os.environ.get("LOCAL_AGENT_DROPBOX_ROOT", "").strip()
    if override:
        candidate = Path(override).expanduser()
        _safe_path(candidate)
        if not candidate.is_dir():
            return None
        return candidate.resolve()
    appdata = os.environ.get("APPDATA")
    if appdata:
        config = Path(appdata) / "Dropbox" / "info.json"
        if config.is_file() and not config.is_symlink():
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
                pass
    # Avoid guessing a user folder: an unrelated directory named "Dropbox"
    # could cause silently exporting private Blender scenes outside Dropbox.
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


def _is_blender_project_file(source: Path, signature: bytes) -> bool:
    """Accept a Blender file header directly or inside bounded gzip data."""
    if signature.startswith(b"BLENDER"):
        return True
    if not signature.startswith(b"\\x1f\\x8b"):
        return False
    try:
        with gzip.open(source, "rb") as stream:
            return stream.read(7).startswith(b"BLENDER")
    except (OSError, EOFError):
        return False


def export_mia_scene_review(workspace: str | Path, project_name: str) -> dict[str, Any]:
    """Copy only the fixed Episode 1 draft .blend and PNG to opted-in Dropbox Sync.

    This is an explicit local Dropbox-review export. It accepts no arbitrary
    source paths, does not include story text, and never overwrites an earlier
    review folder. Dropbox cloud delivery must still be verified separately.
    """
    if project_name != "S01E01_SC01_DRAFT":
        raise ReviewDeliveryError("Only the fixed Episode 1 draft project can be exported")
    if not read_settings()["enabled"]:
        return {"status": "disabled", "reason": "dropbox_review_permission_disabled"}

    workspace_root = Path(workspace).expanduser()
    _safe_path(workspace_root)
    if not workspace_root.is_dir():
        raise ReviewDeliveryError("Workspace is unavailable")
    workspace_root = workspace_root.resolve()
    project = _safe_path(workspace_root / project_name)
    if not project.is_dir() or not project.resolve().is_relative_to(workspace_root):
        raise ReviewDeliveryError("Episode 1 draft project is unavailable or outside the workspace")

    sources = (
        ("scene.blend", _safe_path(project / "mia_blockout.blend"), 128_000_000),
        ("preview.png", _safe_path(project / "mia_blockout.png"), 20_000_000),
    )
    metadata = []
    for name, source, limit in sources:
        if not source.is_file():
            raise ReviewDeliveryError("Required scene artifact is missing")
        size = source.stat().st_size
        if size <= 0 or size > limit:
            raise ReviewDeliveryError("Scene artifact is empty or exceeds its export size limit")
        with source.open("rb") as stream:
            signature = stream.read(8)
        if name == "scene.blend" and not _is_blender_project_file(source, signature):
            raise ReviewDeliveryError("Scene project is not a Blender file")
        if name == "preview.png" and signature != bytes.fromhex("89504e470d0a1a0a"):
            raise ReviewDeliveryError("Scene preview is not a PNG file")
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        metadata.append({"name": name, "size_bytes": size, "sha256": digest.hexdigest()})

    root = discover_dropbox_root()
    if root is None:
        raise ReviewDeliveryError("Dropbox Desktop folder was not detected; sign in to Dropbox desktop")
    review_root = _safe_path(root / REVIEW_FOLDER)
    review_root.mkdir(exist_ok=True)
    if len(list(review_root.iterdir())) >= MAX_REVIEW_JOBS:
        raise ReviewDeliveryError("Review folder limit reached; manually archive older reviews")
    job_id = uuid.uuid4().hex
    destination = _safe_path(review_root / job_id)
    if destination.exists():
        raise ReviewDeliveryError("Review job already exists; refusing to overwrite")
    destination.mkdir()
    try:
        for (name, source, _), item in zip(sources, metadata):
            shutil.copyfile(source, destination / name)
            # Re-hash the copied bytes so the published manifest describes
            # the actual Dropbox-sync files, not only the source files.
            copied = hashlib.sha256()
            with (destination / name).open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    copied.update(chunk)
            if copied.hexdigest() != item["sha256"]:
                raise ReviewDeliveryError("Scene artifact changed during export")
        manifest = {
            "status": "draft",
            "scene_id": "S01_SC01",
            "project_name": project_name,
            "manual_visual_review_required": True,
            "files": metadata,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
        (destination / "scene_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (destination / "complete.json").write_text(
            json.dumps({"status": "completed", "job_id": job_id}) + "\n", encoding="utf-8")
        return {
            "status": "exported_to_local_dropbox",
            "folder": REVIEW_FOLDER + "/" + job_id,
            "files": [item["name"] for item in metadata] + ["scene_manifest.json", "complete.json"],
            "sha256": {item["name"]: item["sha256"] for item in metadata},
            "cloud_sync_verified": False,
        }
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


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
        _ffmpeg([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-i", str(video), "-vf", "fps=1,scale=180:-2,tile=4x3",
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
