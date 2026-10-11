"""Durable, bounded localhost Blender scene jobs; no cloud execution."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from local_agent.prompt_interpreter import interpret_scene

_TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class StudioJobError(ValueError):
    pass


class StudioJobs:
    """One active Blender subprocess per studio process, persistent status per job."""

    def __init__(self, store):
        self.store = store
        self.root = store.root / "studio_jobs"
        if self.root.is_symlink() or getattr(self.root, "is_junction", lambda: False)():
            raise StudioJobError("Unsafe jobs directory")
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.active = None
        self.process = None
        self.cancelled = set()

    def latest(self) -> dict[str, Any] | None:
        path = self.root / "latest.json"
        if path.is_symlink() or not path.is_file():
            return None
        try:
            job_id = json.loads(path.read_text(encoding="utf-8"))["job_id"]
            return self.status(job_id)
        except (StudioJobError, OSError, ValueError, KeyError, TypeError):
            return None

    def _path(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
            raise StudioJobError("Invalid job ID")
        d = self.root / job_id
        if d.is_symlink() or getattr(d, "is_junction", lambda: False)():
            raise StudioJobError("Unsafe job path")
        return d

    def _write(self, directory: Path, info: dict[str, Any]):
        dest = directory / "job.json"
        if dest.is_symlink() or getattr(dest, "is_junction", lambda: False)():
            raise StudioJobError("Unsafe job status")
        temp = directory / (".status-" + uuid.uuid4().hex + ".tmp")
        with temp.open("x", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, dest)

    def status(self, job_id: str) -> dict[str, Any]:
        d = self._path(job_id)
        p = d / "job.json"
        if p.is_symlink() or not p.is_file():
            raise StudioJobError("Job not found")
        raw = json.loads(p.read_text(encoding="utf-8"))
        with self.lock:
            if raw["state"] in ("queued", "running") and self.active != job_id:
                raw["state"] = "interrupted"
                raw["message"] = "Рендер прерван перезапуском приложения. Запустите сцену заново."
                self._write(d, raw)
            if raw["state"] == "running":
                frames = d / "frames"
                count = len(list(frames.glob("frame_*.png"))) if frames.exists() else 0
                raw["rendered_frames"] = min(count, raw["total_frames"])
                raw["progress_percent"] = min(98, int(98 * count / max(1, raw["total_frames"])))
        return raw

    def start(self, state: dict[str, Any], scene_id: str) -> dict[str, Any]:
        scene = next((x for x in state["scenes"] if x["id"] == scene_id), None)
        if scene is None:
            raise StudioJobError("Scene not found")
        # The editor's duration controls the rendered scene, not unrelated project settings.
        config = dict(state)
        config["settings"] = {**state["settings"], "duration": scene["duration"]}
        plan = interpret_scene(scene["prompt"], config, scene_id)
        if plan["readiness"] != "ready_fixture":
            raise StudioJobError("Сцена не готова: " + "; ".join(plan["missing_requirements"]))
        with self.lock:
            if self.active is not None:
                raise StudioJobError("Другой рендер уже выполняется")
            from local_agent.blender_locator import find_blender_executable
            blender = find_blender_executable()
            if blender is None:
                raise StudioJobError("Blender не установлен или не найден. Проверьте BLENDER_EXECUTABLE")
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise StudioJobError("FFmpeg не найден в PATH")
            job_id = uuid.uuid4().hex
            directory = self._path(job_id)
            directory.mkdir(mode=0o700)
            (directory / "manifest.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            info = {"job_id": job_id, "scene_id": scene_id, "state": "queued",
                    "message": "Ожидает Blender", "progress_percent": 0,
                    "rendered_frames": 0, "total_frames": plan["duration"] * plan["fps"],
                    "label": plan["label"], "output": str(directory), "video_url": ""}
            self._write(directory, info)
            latest_temp = self.root / (".latest-" + uuid.uuid4().hex + ".tmp")
            latest_temp.write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
            if (self.root / "latest.json").is_symlink():
                raise StudioJobError("Unsafe latest status path")
            os.replace(latest_temp, self.root / "latest.json")
            self.active = job_id
            worker = threading.Thread(target=self._run, args=(job_id, directory, blender, ffmpeg), daemon=True)
            worker.start()
            return dict(info)

    def _run(self, job_id: str, d: Path, blender: str, ffmpeg: str):
        info = self.status(job_id)
        try:
            if job_id in self.cancelled:
                raise StudioJobError("Cancelled")
            with self.lock:
                info.update(state="running", message="Blender создаёт анимацию")
                self._write(d, info)
            script = Path(__file__).resolve().with_name("studio_blender_scene.py")
            cmd = [str(blender), "--background", "--factory-startup", "--disable-autoexec",
                   "--python", str(script), "--", str(d / "manifest.json"), str(d)]
            with (d / "blender.log").open("w", encoding="utf-8", errors="replace") as log:
                proc = subprocess.Popen(cmd, cwd=str(d), stdin=subprocess.DEVNULL,
                                        stdout=log, stderr=subprocess.STDOUT, shell=False)
                with self.lock:
                    self.process = proc
                try:
                    code = proc.wait(timeout=3600)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    raise StudioJobError("Blender exceeded the one-hour scene timeout")
            if job_id in self.cancelled:
                raise StudioJobError("Cancelled")
            if code != 0:
                raise StudioJobError(f"Blender exited with code {code}; see blender.log")
            frame_count = len(list((d / "frames").glob("frame_*.png")))
            if frame_count != info["total_frames"] or not (d / "scene.blend").is_file():
                raise StudioJobError(f"Frames incomplete: {frame_count}/{info['total_frames']}")
            with self.lock:
                info.update(message="FFmpeg собирает MP4", progress_percent=98, rendered_frames=frame_count)
                self._write(d, info)
            cmd = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                   "-framerate", str(json.loads((d / "manifest.json").read_text(encoding="utf-8"))["fps"]),
                   "-i", str(d / "frames" / "frame_%04d.png"), "-c:v", "libx264",
                   "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(d / "scene.mp4")]
            with (d / "ffmpeg.log").open("w", encoding="utf-8", errors="replace") as log:
                result = subprocess.run(cmd, cwd=str(d), stdin=subprocess.DEVNULL,
                                        stdout=log, stderr=subprocess.STDOUT, timeout=300, shell=False)
            if job_id in self.cancelled:
                raise StudioJobError("Cancelled")
            if result.returncode != 0 or not (d / "scene.mp4").is_file() or (d / "scene.mp4").stat().st_size < 100:
                raise StudioJobError("FFmpeg did not create a valid MP4; see ffmpeg.log")
            info.update(state="completed", message="Тестовая анимация готова", progress_percent=100,
                        video_url="/api/studio-video/" + job_id)
        except Exception as exc:
            info.update(state="cancelled" if job_id in self.cancelled else "failed", message=str(exc)[:500])
        finally:
            with self.lock:
                self.process = None
                self.active = None
                self.cancelled.discard(job_id)
                self._write(d, info)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            if self.active != job_id:
                raise StudioJobError("Job not running")
            self.cancelled.add(job_id)
            if self.process and self.process.poll() is None:
                self.process.terminate()
        return self.status(job_id)

    def video(self, job_id: str) -> Path:
        info = self.status(job_id)
        if info["state"] != "completed":
            raise StudioJobError("No completed video")
        p = self._path(job_id) / "scene.mp4"
        if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(self.root.resolve()):
            raise StudioJobError("Video missing or unsafe")
        if p.stat().st_size > 500_000_000:
            raise StudioJobError("Video file too large")
        return p
