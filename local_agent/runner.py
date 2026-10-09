"""Sequential scene runner; backend and media tools are injected for testability."""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from threading import Lock
from typing import Any, Protocol

from local_agent.checkpoint import CheckpointStore
from local_agent.manifest import ProjectManifest, SceneSpec
from local_agent.ffmpeg_media import MediaError


class VideoBackend(Protocol):
    async def generate_i2v(
        self, *, prompt: str, input_image: str, duration_seconds: int,
        aspect_ratio: str, output_path: str
    ) -> str: ...


class MediaTools(Protocol):
    def validate_video(self, path: str, expected_duration: int) -> None: ...
    def extract_last_frame(self, video_path: str, output_path: str) -> str: ...
    def validate_image(self, path: str) -> None: ...
    def concatenate(self, video_paths: list[str], output_path: str) -> str: ...


_ACTIVE_PROJECTS_LOCK = Lock()
_ACTIVE_PROJECTS: set[tuple[str, str]] = set()


class LocalProjectRunner:
    """Run dependent scenes in order and never advance without a valid final frame.

    This class does not implement a specific model or FFmpeg command. Those are
    supplied by adapters, allowing the orchestration logic to be tested with mocks.
    """

    def __init__(
        self, workspace: str | os.PathLike[str], store: CheckpointStore,
        backend: VideoBackend, media: MediaTools, *, max_attempts: int = 2,
    ):
        if max_attempts < 1 or max_attempts > 10:
            raise ValueError("max_attempts must be between 1 and 10")
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.store = store
        self.backend = backend
        self.media = media
        self.max_attempts = max_attempts
        self._cancel = asyncio.Event()
        self._pause = asyncio.Event()
        self._pause.set()

    def pause(self) -> None:
        self._pause.clear()

    def resume(self) -> None:
        self._pause.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.set()

    async def run(self, manifest: ProjectManifest) -> dict:
        # The registry provides a fast same-process check; the OS lock below
        # also arbitrates ownership across processes on the same local filesystem.
        key = (str(self.workspace.resolve()), manifest.project_id)
        with _ACTIVE_PROJECTS_LOCK:
            if key in _ACTIVE_PROJECTS:
                raise RuntimeError(f"Project {manifest.project_id!r} is already running in this process")
            _ACTIVE_PROJECTS.add(key)
        expected_store_root = (self.workspace / manifest.project_id).resolve()
        if self.store.root.resolve() != expected_store_root:
            with _ACTIVE_PROJECTS_LOCK:
                _ACTIVE_PROJECTS.discard(key)
            raise ValueError("CheckpointStore root must match this runner workspace and manifest project")
        lock_path = self.store.root / ".runner.lock"
        lock_handle = None
        try:
            lock_handle = self._acquire_process_lock(lock_path)
            try:
                return await self._run_project(manifest)
            except asyncio.CancelledError:
                self._persist_terminal_state("cancelled", "Runner task was cancelled by its owner")
                raise
            except Exception as exc:
                # Do not strand a checkpoint in "running" if setup, input validation,
                # a checkpoint write, or an unexpected adapter operation fails.
                self._persist_terminal_state("failed", f"{type(exc).__name__}: {exc}"[:2000])
                raise
            finally:
                if lock_handle is not None:
                    self._release_process_lock(lock_handle)
        finally:
            with _ACTIVE_PROJECTS_LOCK:
                _ACTIVE_PROJECTS.discard(key)

    def _persist_terminal_state(self, status: str, error: str) -> None:
        try:
            state = self.store.load()
            if state is None or state.get("status") in {"completed", "failed", "cancelled"}:
                return
            state["status"] = status
            state["error"] = error
            self.store.save(state)
            self.store.event(f"project_{status}", {"error": error})
        except Exception:
            # Preserve the original exception/cancellation; recovery can inspect
            # the last durable checkpoint if the storage layer itself has failed.
            pass

    @staticmethod
    def _acquire_process_lock(lock_path: Path) -> Any:
        """Acquire a kernel-managed, non-blocking lock released automatically on process exit."""
        stream = lock_path.open("a+b")
        try:
            # Windows byte-range locks require at least one byte. Concurrent writes
            # of this sentinel are harmless; the lock itself arbitrates ownership.
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\\0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return stream
        except (OSError, BlockingIOError) as exc:
            stream.close()
            raise RuntimeError("Project is locked by another process; refusing concurrent execution") from exc
        except BaseException:
            stream.close()
            raise

    @staticmethod
    def _release_process_lock(stream: Any) -> None:
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

    async def _run_project(self, manifest: ProjectManifest) -> dict:
        state = self.store.initialize(manifest.to_dict())
        project_dir = self.workspace / manifest.project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        # Reject pre-existing symlinks/junctions that redirect outputs outside the workspace.
        resolved_project_dir = project_dir.resolve()
        if not resolved_project_dir.is_relative_to(self.workspace):
            raise ValueError("Project output directory resolves outside the configured workspace")
        project_dir = resolved_project_dir

        def project_output_path(value: str, *, label: str) -> str:
            candidate = Path(value).resolve()
            if not candidate.is_relative_to(project_dir):
                raise ValueError(f"{label} resolves outside the project output directory")
            return str(candidate)

        previous_frame = manifest.initial_image

        if previous_frame:
            self.media.validate_image(previous_frame)
        elif manifest.scenes:
            raise ValueError("An initial_image is required until an image-generation resolver is configured")

        state["status"] = "running"
        self.store.save(state)
        self.store.event("project_started", {"scene_count": len(manifest.scenes)})

        video_paths: list[str] = []
        for index, scene in enumerate(manifest.scenes, start=1):
            if self._cancel.is_set():
                state["status"] = "cancelled"
                self.store.save(state)
                self.store.event("project_cancelled", {"next_scene_index": index})
                return state

            await self._pause.wait()
            if self._cancel.is_set():
                state["status"] = "cancelled"
                self.store.save(state)
                return state

            scene_state = state["scenes"][scene.scene_id]
            saved_video = scene_state.get("video_path")
            saved_frame = scene_state.get("final_frame_path")
            checkpoint_path_error = None
            try:
                if saved_video:
                    saved_video = project_output_path(saved_video, label="Checkpoint video path")
                if saved_frame:
                    saved_frame = project_output_path(saved_frame, label="Checkpoint frame path")
            except ValueError as exc:
                # Treat untrusted checkpoint paths as invalid cached outputs; never
                # open them, and regenerate the scene from the verified input frame.
                checkpoint_path_error = str(exc)
                saved_video = None
                saved_frame = None
                self.store.update_scene(
                    state, scene.scene_id, status="pending", error=checkpoint_path_error,
                    video_path=None, final_frame_path=None,
                    video_sha256=None, frame_sha256=None, input_frame_sha256=None,
                )
                self.store.event("scene_checkpoint_path_rejected", {
                    "scene_id": scene.scene_id, "index": index, "error": checkpoint_path_error,
                })
            current_input_hash = (
                self._sha256_file(previous_frame)
                if previous_frame and os.path.isfile(previous_frame) else None
            )
            if scene_state.get("status") == "completed" and saved_video and saved_frame and os.path.isfile(saved_video) and os.path.isfile(saved_frame):
                reuse_error = None
                try:
                    self.media.validate_video(saved_video, scene.duration_seconds)
                    self.media.validate_image(saved_frame)
                    video_hash = self._sha256_file(saved_video)
                    frame_hash = self._sha256_file(saved_frame)
                    if not current_input_hash:
                        reuse_error = "Current input frame is missing; saved scene cannot be safely reused"
                    elif scene_state.get("input_frame_sha256") != current_input_hash:
                        # A prior scene may have been regenerated after a crash or
                        # invalid output. Never reuse downstream clips from an old chain.
                        reuse_error = "Saved scene was generated from a different input frame"
                    elif ((scene_state.get("video_sha256") and scene_state["video_sha256"] != video_hash) or
                            (scene_state.get("frame_sha256") and scene_state["frame_sha256"] != frame_hash)):
                        reuse_error = "Saved output checksum mismatch"
                except Exception as exc:
                    reuse_error = f"Saved output failed revalidation: {type(exc).__name__}: {exc}"[:1000]
                if reuse_error:
                    self.store.update_scene(
                        state, scene.scene_id, status="pending", error=reuse_error,
                        video_path=None, final_frame_path=None,
                        video_sha256=None, frame_sha256=None, input_frame_sha256=None,
                    )
                    self.store.event("scene_checkpoint_output_invalid", {
                        "scene_id": scene.scene_id, "index": index, "error": reuse_error,
                    })
                else:
                    self.store.update_scene(state, scene.scene_id, video_sha256=video_hash, frame_sha256=frame_hash)
                    video_paths.append(saved_video)
                    previous_frame = saved_frame
                    continue

            if not previous_frame or not os.path.isfile(previous_frame):
                state["status"] = "failed"
                state["error"] = f"Scene {index} is blocked: previous final frame is missing"
                self.store.update_scene(state, scene.scene_id, status="failed", error=state["error"])
                self.store.save(state)
                self.store.event("scene_blocked_missing_input", {"scene_id": scene.scene_id, "index": index})
                return state

            final_error: str | None = None
            succeeded = False
            attempt_base = int(scene_state.get("attempts", 0) or 0)
            attempts_left = max(0, self.max_attempts - attempt_base)
            if attempts_left == 0:
                final_error = scene_state.get("error") or "Configured total attempt limit has already been reached"
                self.store.update_scene(state, scene.scene_id, status="failed", error=final_error)
            for retry_index in range(1, attempts_left + 1):
                attempt = attempt_base + retry_index
                if self._cancel.is_set():
                    state["status"] = "cancelled"
                    self.store.save(state)
                    return state
                await self._pause.wait()
                scene_dir = project_dir / scene.scene_id
                scene_dir.mkdir(parents=True, exist_ok=True)
                video_path = project_output_path(
                    str(scene_dir / f"attempt_{attempt:02d}.mp4"),
                    label="Backend output target",
                )
                frame_path = project_output_path(
                    str(scene_dir / f"attempt_{attempt:02d}_last.png"),
                    label="Extracted frame target",
                )
                prompt = self._compose_prompt(manifest.global_prompt, scene)
                self.store.update_scene(
                    state, scene.scene_id, status="running", attempts=attempt, error=None
                )
                self.store.event("scene_generation_started", {"scene_id": scene.scene_id, "index": index, "attempt": attempt})
                try:
                    returned_path = await self.backend.generate_i2v(
                        prompt=prompt, input_image=previous_frame,
                        duration_seconds=scene.duration_seconds,
                        aspect_ratio=scene.aspect_ratio, output_path=video_path,
                    )
                    # A pause requested during generation takes effect after the
                    # current backend call returns; cancellation takes precedence.
                    await self._pause.wait()
                    if self._cancel.is_set():
                        self.store.update_scene(state, scene.scene_id, status="cancelled", error="Cancelled after generation returned")
                        state["status"] = "cancelled"
                        state["error"] = "Cancelled after generation returned"
                        self.store.save(state)
                        self.store.event("project_cancelled", {"scene_id": scene.scene_id, "phase": "post_generation"})
                        return state
                    if not returned_path:
                        raise RuntimeError("Backend returned no video path")
                    returned_path = project_output_path(returned_path, label="Backend video path")
                    if not os.path.isfile(returned_path):
                        raise RuntimeError("Backend returned no readable video file")
                    self.store.update_scene(state, scene.scene_id, status="validating")
                    self.media.validate_video(returned_path, scene.duration_seconds)
                    extracted = self.media.extract_last_frame(returned_path, frame_path)
                    extracted = project_output_path(extracted, label="Extracted frame path")
                    if self._cancel.is_set():
                        self.store.update_scene(state, scene.scene_id, status="cancelled", error="Cancelled during frame extraction")
                        state["status"] = "cancelled"
                        state["error"] = "Cancelled during frame extraction"
                        self.store.save(state)
                        self.store.event("project_cancelled", {"scene_id": scene.scene_id, "phase": "frame_extraction"})
                        return state
                    if not extracted or not os.path.isfile(extracted):
                        raise RuntimeError("Final frame extraction returned no readable image")
                    self.media.validate_image(extracted)
                    if self._cancel.is_set():
                        self.store.update_scene(state, scene.scene_id, status="cancelled", error="Cancelled after frame validation")
                        state["status"] = "cancelled"
                        state["error"] = "Cancelled after frame validation"
                        self.store.save(state)
                        return state
                    self.store.update_scene(
                        state, scene.scene_id, status="completed",
                        video_path=returned_path, final_frame_path=extracted,
                        video_sha256=self._sha256_file(returned_path),
                        frame_sha256=self._sha256_file(extracted),
                        input_frame_sha256=current_input_hash, error=None,
                    )
                    self.store.event("scene_completed", {"scene_id": scene.scene_id, "index": index, "attempt": attempt})
                    video_paths.append(returned_path)
                    previous_frame = extracted
                    succeeded = True
                    break
                except asyncio.CancelledError:
                    # Cancellation is not a generation failure and must never trigger a retry.
                    self.store.update_scene(state, scene.scene_id, status="cancelled", error="Runner task cancelled")
                    self.store.save(state)
                    raise
                except Exception as exc:  # Validation failures are permanent; backend failures may be transient.
                    final_error = f"{type(exc).__name__}: {exc}"[:2000]
                    permanent = isinstance(exc, (MediaError, ValueError, FileNotFoundError))
                    will_retry = retry_index < attempts_left and not permanent
                    self.store.update_scene(
                        state, scene.scene_id, status="retry_wait" if will_retry else "failed",
                        error=final_error,
                    )
                    self.store.event("scene_attempt_failed", {
                        "scene_id": scene.scene_id, "index": index, "attempt": attempt,
                        "permanent": permanent, "will_retry": will_retry, "error": final_error,
                    })
                    if will_retry:
                        await asyncio.sleep(min(2 ** (retry_index - 1), 10))
                    else:
                        break

            if not succeeded:
                state["status"] = "failed"
                state["error"] = f"Scene {index} failed; attempts used {state['scenes'][scene.scene_id].get('attempts', 0)}/{self.max_attempts}: {final_error}"
                self.store.save(state)
                self.store.event("project_failed_after_scene_failure", {"scene_id": scene.scene_id, "index": index, "error": final_error})
                return state

            state["current_scene_index"] = index
            self.store.save(state)

        if len(video_paths) != len(manifest.scenes):
            state["status"] = "paused"
            state["error"] = "Not all scene videos are available; final assembly was skipped"
            self.store.save(state)
            return state

        await self._pause.wait()
        if self._cancel.is_set():
            state["status"] = "cancelled"
            state["error"] = "Cancelled before final assembly"
            self.store.save(state)
            self.store.event("project_cancelled", {"phase": "before_assembly"})
            return state
        # Resolve the destination before FFmpeg opens it: an existing symlink
        # must not redirect writes outside this project's output directory.
        final_path = project_output_path(
            str(project_dir / manifest.output_name), label="Final video target"
        )
        try:
            assembled = self.media.concatenate(video_paths, final_path)
            assembled = project_output_path(assembled, label="Assembled video path")
            if self._cancel.is_set():
                state["status"] = "cancelled"
                state["error"] = "Cancelled during final assembly"
                self.store.save(state)
                self.store.event("project_cancelled", {"phase": "assembly"})
                return state
            if not assembled or not os.path.isfile(assembled) or os.path.getsize(assembled) == 0:
                raise RuntimeError("Final video assembly returned no valid file")
            self.media.validate_video(assembled, sum(scene.duration_seconds for scene in manifest.scenes))
            state["final_video_path"] = assembled
            state["status"] = "completed"
            state["error"] = None
            self.store.save(state)
            self.store.event("project_completed", {"scene_count": len(manifest.scenes), "final_video_path": assembled})
        except Exception as exc:
            state["status"] = "failed"
            state["error"] = f"Final assembly failed: {type(exc).__name__}: {exc}"[:2000]
            self.store.save(state)
            self.store.event("project_assembly_failed", {"error": state["error"]})
        return state

    @staticmethod
    def _sha256_file(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _compose_prompt(global_prompt: str, scene: SceneSpec) -> str:
        continuity = (
            "Continue naturally from the supplied input frame. Preserve the same character identity, age, face, clothing, visual style, lighting and scene geography. "
            "Maintain plausible motion direction and spatial continuity; do not restart the action or introduce an unexplained jump cut. "
            "The input image is the first-frame reference for this scene."
        )
        parts = [part.strip() for part in (global_prompt, scene.prompt, continuity) if part and part.strip()]
        return "\n\n".join(parts)