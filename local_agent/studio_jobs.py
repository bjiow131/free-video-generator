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
    started = active.get("started_at")
    if isinstance(started, (int, float)) and time.time() - started > 7200:
        return {**active, "state": "interrupted",
                "message": "Задача не сообщала о состоянии более двух часов."}
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


class AssetQualityStore:
    """Version-bound visual approvals; Astra cannot grant owner approval to Mia."""
    MIA_REFERENCE_SHA = '7a3194accfecdb4873bc7d4cd8015edb5a94075ca05c72013c5ad97b4a32e383'

    def __init__(self, project_root):
        self.root = Path(project_root).resolve()
        self.directory = self.root/'asset_quality'
        if self.directory.is_symlink() or getattr(self.directory,'is_junction',lambda:False)():
            raise StudioJobError('Unsafe quality directory')
        self.directory.mkdir(parents=True,exist_ok=True)
        self.lock = threading.RLock()

    def _record_path(self, asset_id):
        if not isinstance(asset_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}',asset_id):
            raise StudioJobError('Invalid quality asset ID')
        path=self.directory/(asset_id+'.json')
        if path.is_symlink():
            raise StudioJobError('Unsafe quality record')
        return path

    def _hash(self, relative):
        path=Path(relative)
        if path.is_absolute() or '..' in path.parts or not path.parts:
            raise StudioJobError('Asset path must be project-relative')
        full=self.root/path
        parent=full
        while parent!=self.root:
            if parent.is_symlink() or getattr(parent,'is_junction',lambda:False)():
                raise StudioJobError('Linked asset path rejected')
            parent=parent.parent
        if not full.is_file() or not full.resolve().is_relative_to(self.root) or full.stat().st_size>1_000_000_000:
            raise StudioJobError('Missing or oversized asset')
        with full.open('rb') as stream:
            return hashlib.file_digest(stream,'sha256').hexdigest()

    def _write(self, asset_id, record):
        target=self._record_path(asset_id)
        temporary=self.directory/('.quality-'+uuid.uuid4().hex+'.tmp')
        with temporary.open('x',encoding='utf-8') as stream:
            json.dump(record,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,target)
        return record

    def snapshot(self, asset_id):
        path=self._record_path(asset_id)
        if not path.is_file():
            return {'asset_id':asset_id,'status':'unreviewed'}
        if path.stat().st_size>64000:
            raise StudioJobError('Oversized quality record')
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('asset_id')!=asset_id:
            raise StudioJobError('Quality record identity mismatch')
        try:
            changed=(self._hash(data['source_path'])!=data['source_sha256'] or
                     self._hash(data['candidate_path'])!=data['candidate_sha256'] or
                     any(self._hash(path)!=digest for path,digest in data.get('views',{}).items()))
        except (OSError,KeyError,StudioJobError):
            changed=True
        if changed:
            return {**data,'status':'version_changed_requires_review'}
        return data

    def register(self, asset_id, source_path, candidate_path, views):
        with self.lock:
            if not isinstance(views,list) or not 1<=len(views)<=12:
                raise StudioJobError('Actual rendered views required')
            source_sha=self._hash(source_path)
            if asset_id.startswith('char.mia.') and source_sha!=self.MIA_REFERENCE_SHA:
                raise StudioJobError('Mia source identity mismatch')
            record={'asset_id':asset_id,'source_path':source_path,'source_sha256':source_sha,
                    'candidate_path':candidate_path,'candidate_sha256':self._hash(candidate_path),
                    'views':{path:self._hash(path) for path in views},'status':'awaiting_astra_review',
                    'user_approved':False,'astra_review':None,'updated_at':time.time()}
            return self._write(asset_id,record)

    def record_astra_review(self, asset_id, *, source_sha256, candidate_sha256,
                            view_hashes, vision_confirmed, criteria, unresolved):
        with self.lock:
            record=self.snapshot(asset_id)
            if record['status'] in ('unreviewed','version_changed_requires_review'):
                raise StudioJobError('Review does not match current asset version')
            if (record['source_sha256']!=source_sha256 or record['candidate_sha256']!=candidate_sha256
                    or record['views']!=view_hashes):
                raise StudioJobError('Review evidence hashes mismatch')
            if (type(vision_confirmed) is not bool or not isinstance(criteria,dict) or
                not criteria or any(type(v) is not bool for v in criteria.values()) or
                not isinstance(unresolved,list) or any(not isinstance(x,str) or len(x)>300 for x in unresolved)):
                raise StudioJobError('Invalid visual review evidence')
            accepted=vision_confirmed and all(criteria.values()) and not unresolved
            status=('awaiting_mia_owner_approval' if asset_id.startswith('char.mia.') else 'astra_approved') if accepted else 'needs_revision'
            record.update(status=status,user_approved=False,updated_at=time.time(),
                astra_review={'vision_confirmed':vision_confirmed,'criteria':criteria,'unresolved':unresolved})
            return self._write(asset_id,record)

    def owner_approve_mia(self, asset_id, expected_candidate_sha256):
        with self.lock:
            record=self.snapshot(asset_id)
            if not asset_id.startswith('char.mia.') or record['status']!='awaiting_mia_owner_approval' or record['candidate_sha256']!=expected_candidate_sha256:
                raise StudioJobError('Mia must match the reviewed candidate')
            record.update(status='user_approved',user_approved=True,updated_at=time.time())
            return self._write(asset_id,record)

    def ready(self, asset_id):
        status=self.snapshot(asset_id)['status']
        return status=='user_approved' if asset_id.startswith('char.mia.') else status in ('astra_approved','user_approved')



class SeasonFeedbackCoordinator:
    """Durable ask -> execute -> verify -> feedback loop with exactly 30 episode gates.

    Provider and executor adapters must supply actual implementations. This class
    never treats model claims or a plan as episode completion.
    """
    EPISODES = tuple(f'S01E{i:02d}' for i in range(1,31))

    def __init__(self, project_root):
        self.root=Path(project_root).resolve()
        self.directory=self.root/'season_control'
        if self.directory.is_symlink() or getattr(self.directory,'is_junction',lambda:False)():
            raise StudioJobError('Unsafe season control directory')
        self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/'state.json'
        self.lock=threading.RLock()

    def snapshot(self):
        if self.path.is_symlink():
            raise StudioJobError('Unsafe season state')
        if not self.path.is_file():
            return {'schema_version':1,'status':'not_started','episodes':{k:'pending' for k in self.EPISODES},
                    'actions':{},'pending_action':None,'last_feedback':None,'cycle':0}
        if self.path.stat().st_size>4_000_000:
            raise StudioJobError('Season snapshot capacity reached; archive before continuing')
        data=json.loads(self.path.read_text(encoding='utf-8'))
        if set(data.get('episodes',{}))!=set(self.EPISODES):
            raise StudioJobError('Expected exactly 30 episode records')
        return data

    def _persist(self,state,event):
        from local_agent.reporting import _redact_value
        state=_redact_value(state)
        record=_redact_value({'at':time.time(),**event})
        journal=self.directory/'history.jsonl'
        if journal.is_symlink():
            raise StudioJobError('Unsafe season history')
        with journal.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(record,ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
        temp=self.directory/('.state-'+uuid.uuid4().hex+'.tmp')
        with temp.open('x',encoding='utf-8') as stream:
            json.dump(state,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,self.path)

    def start(self):
        with self.lock:
            state=self.snapshot()
            if state['status']=='not_started':
                state['status']='ready';self._persist(state,{'event':'season_started','goal':30})
            return state

    def cycle_once(self, ask_astra, executors, verify_episode):
        with self.lock:
            state=self.start()
            if state['status']=='completed':
                return state
            if state['pending_action']:
                # A crash does not establish whether a side effect happened.
                pending=state['pending_action'];state['pending_action']=None
                state['status']='needs_reconciliation'
                state['last_feedback']={'status':'execution_outcome_uncertain','action':pending,
                    'instruction':'Inspect actual artifacts before issuing a retry with a new action ID.'}
                self._persist(state,{'event':'interrupted_action_reconciliation','action':pending})
                return state
            question={'goal':'30 verified complete episodes','episodes':state['episodes'],
                      'feedback':state['last_feedback'],'supported_operations':sorted(executors),
                      'instruction':'Return one JSON action with action_id, operation, arguments. Use feedback and inspect actual artifacts; unsupported commands are never executed.'}
            self._persist(state,{'event':'astra_request','request':question})
        # API and side effects run outside the snapshot lock.
        reply=ask_astra(question)
        if not isinstance(reply,dict) or set(reply)!={'action_id','operation','arguments'}:
            raise StudioJobError('Invalid production action envelope')
        identifier=reply['action_id']
        if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}',identifier) or not isinstance(reply['operation'],str) or not isinstance(reply['arguments'],dict):
            raise StudioJobError('Invalid production action fields')
        from local_agent.reporting import _redact_value
        if _redact_value(reply)!=reply:
            raise StudioJobError('Credentials may not be included in a production action')
        encoded=json.dumps(reply,sort_keys=True,ensure_ascii=False)
        if len(encoded.encode())>64000:
            raise StudioJobError('Production action exceeds limit')
        digest=hashlib.sha256(encoded.encode()).hexdigest()
        with self.lock:
            state=self.snapshot();previous=state['actions'].get(identifier)
            if previous:
                if previous['sha256']!=digest:
                    raise StudioJobError('Immutable action ID reused with different instructions')
                state['last_feedback']={'status':'already_executed_no_replay','action_id':identifier,'result':previous['result']}
                self._persist(state,{'event':'duplicate_action_not_replayed','action_id':identifier})
                return state
            state['pending_action']=reply;state['status']='executing'
            self._persist(state,{'event':'astra_answer_saved_before_execution','answer':reply})
        handler=executors.get(reply['operation'])
        try:
            result=handler(reply['arguments']) if handler else {'status':'blocked','reason':'unsupported_operation'}
            if not isinstance(result,dict):
                raise StudioJobError('Executor must return factual structured evidence')
        except Exception as exc:
            # Keep credentials and arbitrary exception text out of the feedback.
            result={'status':'failed','error_type':type(exc).__name__}
        with self.lock:
            state=self.snapshot()
            state['actions'][identifier]={'sha256':digest,'result':_redact_value(result)}
            state['pending_action']=None;state['cycle']+=1;state['status']='ready'
            state['last_feedback']={'action_id':identifier,'operation':reply['operation'],
                'executed':handler is not None,'result':_redact_value(result)}
            # Verification is a separate local adapter, never a model-returned flag.
            episode=reply['arguments'].get('episode_id')
            if episode in self.EPISODES and result.get('status')=='completed':
                verified=verify_episode(episode,result)
                if verified is True:
                    state['episodes'][episode]='verified_complete'
                else:
                    state['last_feedback']['episode_verification']='failed_or_blocked'
            if all(v=='verified_complete' for v in state['episodes'].values()):
                # Revalidate all recorded complete episodes before season completion.
                valid=all(verify_episode(e,{'revalidate':True}) is True for e in self.EPISODES)
                state['status']='completed' if valid else 'verification_failed'
            self._persist(state,{'event':'execution_verified_and_feedback_saved','feedback':state['last_feedback'],
                                 'episodes':state['episodes'],'status':state['status']})
            return state

    def run(self,ask_astra,executors,verify_episode,stop_event):
        while not stop_event.is_set():
            state=self.cycle_once(ask_astra,executors,verify_episode)
            if state['status'] in ('completed','needs_reconciliation','verification_failed'):
                return state
            # Prevent repeatedly billing for an identical unsupported instruction.
            if state['last_feedback'] and state['last_feedback'].get('status')=='already_executed_no_replay':
                return {**state,'status':'awaiting_new_strategy'}
        return {**self.snapshot(),'status':'paused'}


def verify_episode_artifact(workspace, episode_id, *, ffprobe='ffprobe'):
    """Validate the technical contract for one finished portrait episode.

    This is a hard technical gate, not a visual-quality verdict. The output name
    is fixed per episode, media probing is shell-free, and the returned digest
    binds a later review to the exact file bytes.
    """
    import hashlib
    import json
    import re
    import shutil
    import subprocess
    from pathlib import Path

    if not isinstance(episode_id,str) or not re.fullmatch(r'S01E(?:0[1-9]|[12][0-9]|30)',episode_id):
        return {'status':'blocked','reason':'invalid_episode_id'}
    root=Path(workspace).expanduser().resolve()
    output_dir=root/'episodes'/episode_id
    target=output_dir/'final.mp4'
    for path in (root/'episodes',output_dir,target):
        if path.is_symlink() or getattr(path,'is_junction',lambda:False)():
            return {'status':'blocked','reason':'episode_path_is_link'}
    if not target.is_file() or not target.resolve().is_relative_to(root):
        return {'status':'blocked','reason':'episode_file_missing_or_outside_workspace'}
    try:
        size=target.stat().st_size
    except OSError:
        return {'status':'blocked','reason':'episode_file_unreadable'}
    if size<1_000_000:
        return {'status':'blocked','reason':'episode_file_too_small','size_bytes':size}
    executable=shutil.which(ffprobe) if isinstance(ffprobe,str) else None
    if executable is None:
        return {'status':'blocked','reason':'ffprobe_unavailable'}
    try:
        completed=subprocess.run([executable,'-v','error','-count_frames','-show_entries',
            'format=format_name,duration:stream=codec_type,codec_name,width,height,pix_fmt,avg_frame_rate,nb_read_frames',
            '-of','json',str(target)],capture_output=True,check=False,timeout=90,shell=False)
        if completed.returncode!=0 or len(completed.stdout)>65536:
            return {'status':'blocked','reason':'media_probe_failed'}
        metadata=json.loads(completed.stdout.decode('utf-8'))
        streams=metadata.get('streams')
        info=metadata.get('format')
        if not isinstance(streams,list) or len(streams)!=1 or not isinstance(info,dict):
            return {'status':'blocked','reason':'unexpected_media_streams'}
        video=streams[0]
        if video.get('codec_type')!='video':
            return {'status':'blocked','reason':'video_stream_missing'}
        try:
            duration=float(info['duration']);width=int(video['width']);height=int(video['height'])
            frame_count=int(video['nb_read_frames']);num,den=(int(x) for x in video['avg_frame_rate'].split('/',1))
        except (KeyError,TypeError,ValueError,ZeroDivisionError):
            return {'status':'blocked','reason':'incomplete_media_metadata'}
        fps=num/den
        if not 300<=duration<=600:
            return {'status':'blocked','reason':'episode_duration_out_of_range','duration_seconds':duration}
        if width<720 or height<1280 or abs((width/height)-(9/16))>0.025:
            return {'status':'blocked','reason':'portrait_resolution_out_of_range','width':width,'height':height}
        if video.get('codec_name')!='h264' or video.get('pix_fmt')!='yuv420p' or not 18<=fps<=60:
            return {'status':'blocked','reason':'video_encoding_out_of_range'}
        if frame_count<duration*fps*0.95:
            return {'status':'blocked','reason':'frame_count_incomplete'}
        if 'mp4' not in str(info.get('format_name','')).split(','):
            return {'status':'blocked','reason':'container_is_not_mp4'}
    except (OSError,subprocess.TimeoutExpired,UnicodeError,ValueError,TypeError):
        return {'status':'blocked','reason':'media_probe_unavailable'}
    digest=hashlib.sha256()
    try:
        with target.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):
                digest.update(block)
    except OSError:
        return {'status':'blocked','reason':'episode_hash_failed'}
    return {'status':'technical_checks_passed','episode_id':episode_id,'path':str(target),
        'sha256':digest.hexdigest(),'size_bytes':size,'duration_seconds':duration,
        'width':width,'height':height,'frame_count':frame_count,
        'visual_review_required':True,'season_completion_eligible':False}


