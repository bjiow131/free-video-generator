"""Durable, bounded localhost Blender scene jobs; no cloud execution."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from local_agent.prompt_interpreter import interpret_scene

_TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def _prepare_studio_blender_script(source: Path, job_dir: Path) -> Path:
    """Use a validated temporary compatibility copy on older installations.

    The Windows trusted updater cannot overwrite the Blender-side script.
    Older installed versions create an empty factory scene whose world is None.
    This exact one-line compatibility fix uses only already-installed code and
    writes a private copy inside the new render job. A fixed upstream script is
    used directly without any modifications.
    """
    if source.is_symlink() or not source.is_file():
        raise StudioJobError("Unsafe or missing Blender scene script")
    if source.stat().st_size > 200_000:
        raise StudioJobError("Blender scene script too large")
    original = source.read_text(encoding="utf-8")
    marker = "    scene.world.color = (0.08, 0.11, 0.16)"
    if marker not in original:
        return source
    if original.count(marker) != 1 or "    bpy.ops.wm.read_factory_settings(use_empty=True)" not in original:
        raise StudioJobError("Unexpected Blender scene compatibility signature")
    repaired = original.replace(
        marker,
        '    if scene.world is None:\n'
        '        scene.world = bpy.data.worlds.new("Studio Camera QA World")\n'
        + marker,
    )
    # The replacement is fixed code, not a remote task field. Reject malformed
    # source before Blender launches; never mutate the installed original.
    compile(repaired, str(source), "exec")
    temporary = job_dir / "studio_blender_scene_compat.py"
    if temporary.exists() or temporary.is_symlink():
        raise StudioJobError("Existing Blender compatibility script is unsafe")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(repaired)
    return temporary


def scene_fingerprint(state: dict[str, Any], scene: dict[str, Any]) -> str:
    """Version the exact scene inputs that could affect a rendered clip.

    Ignore unrelated project edits. Reject legacy jobs without a fingerprint
    rather than silently composing footage for a different script.
    """
    characters = set(scene.get("characters", []))
    props = set(scene.get("props", []))
    payload = {
        "scene": scene,
        "settings": state.get("settings", {}),
        "characters": [v for v in state.get("characters", []) if v.get("id") in characters],
        "props": [v for v in state.get("props", []) if v.get("id") in props],
    }
    packed = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


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
            info = {"job_id": job_id, "scene_id": scene_id, "kind": "scene", "state": "queued",
                    "message": "Ожидает Blender", "progress_percent": 0,
                    "rendered_frames": 0, "total_frames": plan["duration"] * plan["fps"],
                    "label": plan["label"], "created_at": time.time(), "output": str(directory), "video_url": "",
                    "scene_fingerprint": scene_fingerprint(state, scene)}
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
            script = _prepare_studio_blender_script(Path(__file__).resolve().with_name("studio_blender_scene.py"), d)
            cmd = [str(blender), "--background", "--factory-startup", "--disable-autoexec",
                   "--offline-mode", "--python-exit-code", "12", "--python", str(script), "--", str(d / "manifest.json"), str(d)]
            with (d / "blender.log").open("w", encoding="utf-8", errors="replace") as log:
                # Check cancellation and spawn under the same lock. Otherwise
                # cancel() can run after the earlier check but before Popen,
                # leaving an untracked Blender process running.
                with self.lock:
                    if job_id in self.cancelled:
                        raise StudioJobError("Cancelled")
                    proc = subprocess.Popen(cmd, cwd=str(d), stdin=subprocess.DEVNULL,
                                            stdout=log, stderr=subprocess.STDOUT, shell=False)
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
                with self.lock:
                    if job_id in self.cancelled:
                        raise StudioJobError("Cancelled")
                    proc = subprocess.Popen(cmd, cwd=str(d), stdin=subprocess.DEVNULL,
                                            stdout=log, stderr=subprocess.STDOUT, shell=False)
                    self.process = proc
                try:
                    code = proc.wait(timeout=300)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    raise StudioJobError("FFmpeg exceeded the five-minute timeout")
            if job_id in self.cancelled:
                raise StudioJobError("Cancelled")
            if code != 0 or not (d / "scene.mp4").is_file() or (d / "scene.mp4").stat().st_size < 100:
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

    def compose(self, state: dict[str, Any]) -> dict[str, Any]:
        """Assemble existing completed scene MP4s in saved storyboard order."""
        scenes = state.get("scenes", [])
        if not isinstance(scenes, list) or not 2 <= len(scenes) <= 80:
            raise StudioJobError("Для монтажа требуется минимум две сцены")
        with self.lock:
            if self.active is not None:
                raise StudioJobError("Другой рендер уже выполняется")
            # Resolve only previously persisted, successfully completed scene jobs.
            chosen = {}
            for directory in sorted(self.root.iterdir(), key=lambda p: p.name):
                if not directory.is_dir() or directory.is_symlink() or len(directory.name) != 32:
                    continue
                try:
                    job = self.status(directory.name)
                    if job.get("state") != "completed" or job.get("kind", "scene") != "scene":
                        continue
                    previous = chosen.get(job["scene_id"])
                    if previous is None or job.get("created_at", 0) > previous[1].get("created_at", 0):
                        chosen[job["scene_id"]] = (directory, job)
                except (StudioJobError, ValueError, OSError, KeyError):
                    continue
            video_paths = []
            configurations = []
            for scene in scenes:
                scene_id = scene["id"]
                if scene_id not in chosen:
                    raise StudioJobError(f"Сцена {scene_id} ещё не имеет готового MP4")
                directory, job = chosen[scene_id]
                if job.get("scene_fingerprint") != scene_fingerprint(state, scene):
                    raise StudioJobError(
                        f"Сцена {scene_id} изменена после рендера или создана старой версией. "
                        "Пересоздайте MP4 этой сцены."
                    )
                video_paths.append(self.video(job["job_id"]))
                configurations.append(json.loads((directory / "manifest.json").read_text(encoding="utf-8")))
            settings = {(x["fps"], x["resolution"]) for x in configurations}
            if len(settings) != 1:
                raise StudioJobError("Для монтажа все сцены должны иметь одинаковые FPS и разрешение")
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise StudioJobError("FFmpeg не найден в PATH")
            job_id = uuid.uuid4().hex
            directory = self._path(job_id)
            directory.mkdir(mode=0o700)
            total_frames = sum(x["fps"] * x["duration"] for x in configurations)
            info = {"job_id": job_id, "scene_id": "project", "kind": "assembly", "state": "queued",
                    "message": "Монтаж готовых сцен", "progress_percent": 0,
                    "rendered_frames": 0, "total_frames": total_frames,
                    "label": "Проект из готовых сцен", "created_at": time.time(), "output": str(directory), "video_url": ""}
            self._write(directory, info)
            latest_temp = self.root / (".latest-" + uuid.uuid4().hex + ".tmp")
            latest_temp.write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
            os.replace(latest_temp, self.root / "latest.json")
            self.active = job_id
            threading.Thread(target=self._assemble, args=(info, video_paths, ffmpeg), daemon=True).start()
            return dict(info)

    def _assemble(self, info: dict[str, Any], video_paths: list[Path], ffmpeg: str):
        job_id = info["job_id"]
        directory = self._path(job_id)
        try:
            with self.lock:
                info.update(state="running", message="FFmpeg собирает сцены по порядку")
                self._write(directory, info)
            cmd = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
            for video in video_paths:
                cmd.extend(["-i", str(video)])
            inputs = "".join(f"[{i}:v:0]" for i in range(len(video_paths)))
            cmd.extend(["-filter_complex", f"{inputs}concat=n={len(video_paths)}:v=1:a=0[outv]",
                        "-map", "[outv]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(directory / "scene.mp4")])
            with (directory / "ffmpeg.log").open("w", encoding="utf-8", errors="replace") as log:
                with self.lock:
                    if job_id in self.cancelled:
                        raise StudioJobError("Cancelled")
                    proc = subprocess.Popen(cmd, cwd=str(directory), stdin=subprocess.DEVNULL,
                                            stdout=log, stderr=subprocess.STDOUT, shell=False)
                    self.process = proc
                try:
                    code = proc.wait(timeout=1800)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    raise StudioJobError("Монтаж превысил 30 минут")
            if job_id in self.cancelled:
                raise StudioJobError("Cancelled")
            video = directory / "scene.mp4"
            if code != 0 or not video.is_file() or video.stat().st_size < 100:
                raise StudioJobError("FFmpeg не смог объединить сцены; см. ffmpeg.log")
            info.update(state="completed", message="Все сцены собраны в MP4", progress_percent=100,
                        rendered_frames=info["total_frames"], video_url="/api/studio-video/"+job_id)
        except Exception as exc:
            info.update(state="cancelled" if job_id in self.cancelled else "failed", message=str(exc)[:500])
        finally:
            with self.lock:
                self.process = None
                self.active = None
                self.cancelled.discard(job_id)
                self._write(directory, info)

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
        if p.stat().st_size > 100_000_000:
            raise StudioJobError("Video file too large")
        return p

_AGENT_CONTROL_ROOT = Path(__file__).resolve().parents[1] / ".local_agent"
_AGENT_ACTIVE_TASK = _AGENT_CONTROL_ROOT / "active_agent_task.json"
_AGENT_CANCEL_TASK = _AGENT_CONTROL_ROOT / "cancel_agent_task.json"
_AGENT_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")

def _agent_control_dir() -> Path:
    root = Path(__file__).resolve().parents[1]
    directory = _AGENT_CONTROL_ROOT
    if (root.is_symlink() or getattr(root, "is_junction", lambda: False)()
            or directory.is_symlink() or getattr(directory, "is_junction", lambda: False)()):
        raise StudioJobError("Unsafe agent control directory")
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve().is_relative_to(root.resolve()):
        raise StudioJobError("Agent control directory leaves installation")
    return directory

def _read_agent_control(path: Path) -> dict[str, Any] | None:
    _agent_control_dir()
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise StudioJobError("Unsafe agent control file")
    try:
        if path.stat().st_size > 4096:
            raise StudioJobError("Agent control file is too large")
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, UnicodeError) as exc:
        raise StudioJobError("Agent control file cannot be read") from exc
    if (not isinstance(value, dict) or not isinstance(value.get("task_id"), str)
            or not _AGENT_TASK_ID.fullmatch(value["task_id"])):
        raise StudioJobError("Agent control file is invalid")
    return value

def _write_agent_control(path: Path, value: dict[str, Any]) -> None:
    directory = _agent_control_dir()
    if path.parent.resolve() != directory.resolve() or path.is_symlink():
        raise StudioJobError("Unsafe agent control target")
    temporary = directory / (".agent-control-" + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def agent_task_status() -> dict[str, Any]:
    active = _read_agent_control(_AGENT_ACTIVE_TASK)
    if active is None:
        return {"state": "idle"}
    pid = active.get("pid")
    if type(pid) is int and pid > 0:
        try:
            os.kill(pid, 0)
        except OSError:
            return {**active, "state": "interrupted",
                    "message": "Агент завершился до конца задачи."}
    cancel = _read_agent_control(_AGENT_CANCEL_TASK)
    if cancel and cancel.get("task_id") == active["task_id"]:
        active = {**active, "state": "cancelling"}
    return active

def begin_agent_task(task_id: str, operation: str, project_name: str | None = None) -> dict[str, Any]:
    if not isinstance(task_id, str) or not _AGENT_TASK_ID.fullmatch(task_id):
        raise StudioJobError("Invalid agent task ID")
    current = agent_task_status()
    if current.get("state") in ("running", "cancelling"):
        raise StudioJobError("Another agent task is already active")
    _agent_control_dir()
    cancel = _read_agent_control(_AGENT_CANCEL_TASK)
    if cancel is not None:
        _AGENT_CANCEL_TASK.unlink(missing_ok=True)
    active = {"task_id": task_id, "operation": str(operation)[:80],
              "project_name": str(project_name or "")[:80], "state": "running",
              "pid": os.getpid(), "started_at": time.time()}
    _write_agent_control(_AGENT_ACTIVE_TASK, active)
    return active

def finish_agent_task(task_id: str) -> None:
    active = _read_agent_control(_AGENT_ACTIVE_TASK)
    if active and active.get("task_id") == task_id:
        _AGENT_ACTIVE_TASK.unlink(missing_ok=True)
    cancel = _read_agent_control(_AGENT_CANCEL_TASK)
    if cancel and cancel.get("task_id") == task_id:
        _AGENT_CANCEL_TASK.unlink(missing_ok=True)

def request_agent_task_cancel(task_id: str) -> dict[str, Any]:
    if not isinstance(task_id, str) or not _AGENT_TASK_ID.fullmatch(task_id):
        raise StudioJobError("Invalid agent task ID")
    active = _read_agent_control(_AGENT_ACTIVE_TASK)
    if active is None or active.get("task_id") != task_id or active.get("state") != "running":
        raise StudioJobError("Agent task is not running")
    request = {"task_id": task_id, "requested_at": time.time()}
    _write_agent_control(_AGENT_CANCEL_TASK, request)
    return {**active, "state": "cancelling"}

def agent_task_cancel_requested(task_id: str | None) -> bool:
    if not isinstance(task_id, str) or not task_id:
        return False
    request = _read_agent_control(_AGENT_CANCEL_TASK)
    return bool(request and request.get("task_id") == task_id)
