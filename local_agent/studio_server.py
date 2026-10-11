"""Loopback-only Blender studio UI (standard library; no cloud dependency)."""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import shutil
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
from local_agent.studio_jobs import StudioJobs, StudioJobError
from local_agent.prompt_interpreter import interpret_scene, PromptError
from local_agent.octava_credentials import OctavaKeyError, key_status, replace_key
from local_agent.mailbox_policy import (
    MailboxPolicyError, load_policy, save_policy,
    get_trusted_update_opt_in as get_opt_in,
    set_trusted_update_opt_in as set_opt_in,
)
from datetime import datetime, timezone
import tempfile
import time

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
        if path == "/api/state":
            try:
                return self._json(200, self.server.store.load())
            except StudioError as exc:
                return self._json(500, {"error": str(exc)})
        if path == "/api/studio-latest":
            return self._json(200, {"job": self.server.jobs.latest()})
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
        if path in ("/api/octava-key", "/api/mailbox-policy", "/api/trusted-updates", "/api/dropbox-review") and self.headers.get("Origin") not in (
                f"http://127.0.0.1:{self.server.server_port}",
                f"http://localhost:{self.server.server_port}"):
            return self._json(403, {"error": "Local studio origin required"})
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return self._json(415, {"error": "Expected application/json"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= _MAX_REQUEST or (path == "/api/octava-key" and length > 2700) or (path == "/api/mailbox-policy" and length > 300) or (path == "/api/trusted-updates" and length > 100) or (path == "/api/dropbox-review" and length > 100):
            return self._json(413, {"error": "Invalid request size"})
        try:
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise StudioError("JSON object required")
            if path == "/api/octava-key":
                if set(body) != {"api_key"}:
                    raise StudioError("Укажите только новый API-ключ")
                with self.server.octava_lock:
                    return self._json(200, replace_key(body["api_key"]))
            if path == "/api/mailbox-policy":
                with self.server.mailbox_policy_lock:
                    return self._json(200, save_policy(body))
            if path == "/api/trusted-updates":
                with self.server.mailbox_policy_lock:
                    return self._json(200, set_opt_in(body))
            if path == "/api/dropbox-review":
                with self.server.mailbox_policy_lock:
                    return self._json(200, save_settings(body))
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
        except (StudioError, StudioJobError, PromptError, StoryPlanError, OctavaKeyError, MailboxPolicyError, ReviewDeliveryError, ValueError, TypeError, binascii.Error) as exc:
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
