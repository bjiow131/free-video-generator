"""Sequential scene runner; backend and media tools are injected for testability."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Protocol

from local_agent.checkpoint import CheckpointStore
from local_agent.manifest import ProjectManifest, SceneSpec


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
        state = self.store.initialize(manifest.to_dict())
        project_dir = self.workspace / manifest.project_id
        project_dir.mkdir(parents=True, exist_ok=True)
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
            if scene_state.get("status") == "completed" and saved_video and saved_frame and os.path.isfile(saved_video) and os.path.isfile(saved_frame):
                self.media.validate_video(saved_video, scene.duration_seconds)
                self.media.validate_image(saved_frame)
                video_paths.append(saved_video)
                previous_frame = saved_frame
                continue

            if not previous_frame or not os.path.isfile(previous_frame):
                state["status"] = "paused"
                state["error"] = f"Scene {index} is blocked: previous final frame is missing"
                self.store.update_scene(state, scene.scene_id, status="failed", error=state["error"])
                self.store.save(state)
                self.store.event("scene_blocked_missing_input", {"scene_id": scene.scene_id, "index": index})
                return state

            final_error: str | None = None
            succeeded = False
            for attempt in range(1, self.max_attempts + 1):
                if self._cancel.is_set():
                    state["status"] = "cancelled"
                    self.store.save(state)
                    return state
                await self._pause.wait()
                scene_dir = project_dir / scene.scene_id
                scene_dir.mkdir(parents=True, exist_ok=True)
                video_path = str(scene_dir / f"attempt_{attempt:02d}.mp4")
                frame_path = str(scene_dir / f"attempt_{attempt:02d}_last.png")
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
                    if not returned_path or not os.path.isfile(returned_path):
                        raise RuntimeError("Backend returned no readable video file")
                    self.store.update_scene(state, scene.scene_id, status="validating")
                    self.media.validate_video(returned_path, scene.duration_seconds)
                    extracted = self.media.extract_last_frame(returned_path, frame_path)
                    if not extracted or not os.path.isfile(extracted):
                        raise RuntimeError("Final frame extraction returned no readable image")
                    self.media.validate_image(extracted)
                    self.store.update_scene(
                        state, scene.scene_id, status="completed",
                        video_path=returned_path, final_frame_path=extracted, error=None,
                    )
                    self.store.event("scene_completed", {"scene_id": scene.scene_id, "index": index, "attempt": attempt})
                    video_paths.append(returned_path)
                    previous_frame = extracted
                    succeeded = True
                    break
                except Exception as exc:  # Keep failure local to this scene and retry boundedly.
                    final_error = f"{type(exc).__name__}: {exc}"[:2000]
                    self.store.update_scene(
                        state, scene.scene_id, status="retry_wait" if attempt < self.max_attempts else "failed",
                        error=final_error,
                    )
                    self.store.event("scene_attempt_failed", {"scene_id": scene.scene_id, "index": index, "attempt": attempt, "error": final_error})
                    if attempt < self.max_attempts:
                        await asyncio.sleep(min(2 ** (attempt - 1), 10))

            if not succeeded:
                state["status"] = "paused"
                state["error"] = f"Scene {index} failed after {self.max_attempts} attempts: {final_error}"
                self.store.save(state)
                self.store.event("project_paused_after_scene_failure", {"scene_id": scene.scene_id, "index": index})
                return state

            state["current_scene_index"] = index
            self.store.save(state)

        if len(video_paths) != len(manifest.scenes):
            state["status"] = "paused"
            state["error"] = "Not all scene videos are available; final assembly was skipped"
            self.store.save(state)
            return state

        final_path = str(project_dir / manifest.output_name)
        try:
            assembled = self.media.concatenate(video_paths, final_path)
            if not assembled or not os.path.isfile(assembled) or os.path.getsize(assembled) == 0:
                raise RuntimeError("Final video assembly returned no valid file")
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
    def _compose_prompt(global_prompt: str, scene: SceneSpec) -> str:
        continuity = (
            "Continue naturally from the supplied input frame. Preserve the same character identity, age, face, clothing, visual style, lighting and scene geography. "
            "Maintain plausible motion direction and spatial continuity; do not restart the action or introduce an unexplained jump cut. "
            "The input image is the first-frame reference for this scene."
        )
        parts = [part.strip() for part in (global_prompt, scene.prompt, continuity) if part and part.strip()]
        return "\n\n".join(parts)