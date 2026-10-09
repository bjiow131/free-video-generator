"""Validated project manifest for the computer-only local video agent.

This module intentionally uses only the Python standard library so the agent core
can be tested without the video model, FFmpeg, or the Windows computer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ALLOWED_RATIOS = {"9:16", "16:9", "1:1"}
MAX_SCENES_DEFAULT = 1000


@dataclass(frozen=True)
class SceneSpec:
    scene_id: str
    prompt: str
    duration_seconds: int = 5
    aspect_ratio: str = "9:16"

    @classmethod
    def from_dict(cls, data: dict[str, Any], index: int) -> "SceneSpec":
        if not isinstance(data, dict):
            raise ValueError(f"Scene {index}: expected an object")
        prompt = data.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"Scene {index}: prompt must be a non-empty string")
        if len(prompt) > 12000:
            raise ValueError(f"Scene {index}: prompt exceeds 12000 characters")
        scene_id = str(data.get("scene_id") or f"scene_{index:04d}").strip()
        if not scene_id or len(scene_id) > 128:
            raise ValueError(f"Scene {index}: invalid scene_id")
        try:
            duration = int(data.get("duration_seconds", 5))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Scene {index}: duration_seconds must be an integer") from exc
        if duration < 1 or duration > 120:
            raise ValueError(f"Scene {index}: duration_seconds must be between 1 and 120")
        ratio = str(data.get("aspect_ratio", "9:16"))
        if ratio not in ALLOWED_RATIOS:
            raise ValueError(f"Scene {index}: aspect_ratio must be one of {sorted(ALLOWED_RATIOS)}")
        return cls(scene_id, prompt.strip(), duration, ratio)


@dataclass(frozen=True)
class ProjectManifest:
    project_id: str
    scenes: tuple[SceneSpec, ...]
    initial_image: str | None = None
    global_prompt: str = ""
    output_name: str = "final_video.mp4"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], *, max_scenes: int = MAX_SCENES_DEFAULT
    ) -> "ProjectManifest":
        if not isinstance(data, dict):
            raise ValueError("Project manifest must be an object")
        project_id = str(data.get("project_id") or "").strip()
        if not project_id or len(project_id) > 128:
            raise ValueError("project_id is required and must be at most 128 characters")
        raw_scenes = data.get("scenes")
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise ValueError("scenes must be a non-empty list")
        if len(raw_scenes) > max_scenes:
            raise ValueError(f"Project has {len(raw_scenes)} scenes; limit is {max_scenes}")
        scenes = tuple(SceneSpec.from_dict(item, i + 1) for i, item in enumerate(raw_scenes))
        ids = [scene.scene_id for scene in scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("scene_id values must be unique within a project")
        initial_image = data.get("initial_image")
        if initial_image is not None and not isinstance(initial_image, str):
            raise ValueError("initial_image must be a local path or trusted asset reference string")
        global_prompt = data.get("global_prompt", "")
        if not isinstance(global_prompt, str) or len(global_prompt) > 12000:
            raise ValueError("global_prompt must be a string no longer than 12000 characters")
        output_name = str(data.get("output_name") or "final_video.mp4")
        if output_name in {".", ".."} or output_name != output_name.split("/")[-1] or output_name != output_name.split("\\")[-1]:
            raise ValueError("output_name must be a filename, not a path")
        metadata = data.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        return cls(project_id, scenes, initial_image, global_prompt, output_name, metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "initial_image": self.initial_image,
            "global_prompt": self.global_prompt,
            "output_name": self.output_name,
            "metadata": self.metadata,
            "scenes": [
                {
                    "scene_id": scene.scene_id,
                    "prompt": scene.prompt,
                    "duration_seconds": scene.duration_seconds,
                    "aspect_ratio": scene.aspect_ratio,
                }
                for scene in self.scenes
            ],
        }