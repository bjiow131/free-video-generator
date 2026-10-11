"""Loopback-only Blender studio UI (standard library; no cloud dependency)."""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
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

_STATIC = Path(__file__).resolve().parent / "studio_static"
_MEDIA_NAME = re.compile(r"[a-f0-9]{32}\.(?:png|jpg|webp)\Z")
_IMAGE_MIMES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
_MAX_REQUEST = 4_600_000


class StudioHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store: StudioStore):
        super().__init__(address, StudioHandler)
        self.store = store
        self.jobs = StudioJobs(store)
        self.render_lock = threading.Lock()
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
                return self._send(200, video.read_bytes(), "video/mp4")
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
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return self._json(415, {"error": "Expected application/json"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= _MAX_REQUEST:
            return self._json(413, {"error": "Invalid request size"})
        try:
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise StudioError("JSON object required")
            path = urlsplit(self.path).path
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
        except (StudioError, StudioJobError, PromptError, StoryPlanError, ValueError, TypeError, binascii.Error) as exc:
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
