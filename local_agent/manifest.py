"""Validated, versioned project manifest for the computer-only video agent."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

ALLOWED_RATIOS = {"9:16", "16:9", "1:1"}
MAX_SCENES_DEFAULT = 1000
MANIFEST_SCHEMA_VERSION = 1
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_WINDOWS_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


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
        raw_id = data.get("scene_id") or f"scene_{index:04d}"
        if not isinstance(raw_id, str):
            raise ValueError(f"Scene {index}: scene_id must be a string")
        scene_id = raw_id.strip()
        if not _SAFE_ID.fullmatch(scene_id):
            raise ValueError(f"Scene {index}: scene_id must use only letters, numbers, underscore and hyphen")
        raw_duration = data.get("duration_seconds", 5)
        if isinstance(raw_duration, bool) or not isinstance(raw_duration, int):
            raise ValueError(f"Scene {index}: duration_seconds must be an integer")
        if raw_duration < 1 or raw_duration > 120:
            raise ValueError(f"Scene {index}: duration_seconds must be between 1 and 120")
        ratio = data.get("aspect_ratio", "9:16")
        if not isinstance(ratio, str) or ratio not in ALLOWED_RATIOS:
            raise ValueError(f"Scene {index}: aspect_ratio must be one of {sorted(ALLOWED_RATIOS)}")
        return cls(scene_id, prompt.strip(), raw_duration, ratio)


@dataclass(frozen=True)
class ProjectManifest:
    project_id: str
    scenes: tuple[SceneSpec, ...]
    initial_image: str | None = None
    global_prompt: str = ""
    output_name: str = "final_video.mp4"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = MANIFEST_SCHEMA_VERSION
    project_name: str = ""

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], *, max_scenes: int = MAX_SCENES_DEFAULT
    ) -> "ProjectManifest":
        if not isinstance(data, dict):
            raise ValueError("Project manifest must be an object")
        version = data.get("schema_version", MANIFEST_SCHEMA_VERSION)
        if isinstance(version, bool) or version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"Unsupported manifest schema_version: {version!r}")
        raw_project_id = data.get("project_id")
        if not isinstance(raw_project_id, str) or not _SAFE_ID.fullmatch(raw_project_id.strip()):
            raise ValueError("project_id is required and must use only letters, numbers, underscore and hyphen")
        project_id = raw_project_id.strip()
        raw_scenes = data.get("scenes")
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise ValueError("scenes must be a non-empty list")
        if not isinstance(max_scenes, int) or max_scenes < 1:
            raise ValueError("max_scenes must be a positive integer")
        if len(raw_scenes) > max_scenes:
            raise ValueError(f"Project has {len(raw_scenes)} scenes; limit is {max_scenes}")
        scenes = tuple(SceneSpec.from_dict(item, i + 1) for i, item in enumerate(raw_scenes))
        ids = [scene.scene_id for scene in scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("scene_id values must be unique within a project")
        initial_image = data.get("initial_image")
        if initial_image is not None and (not isinstance(initial_image, str) or not initial_image.strip()):
            raise ValueError("initial_image must be a non-empty local path or trusted asset reference string")
        global_prompt = data.get("global_prompt", "")
        if not isinstance(global_prompt, str) or len(global_prompt) > 12000:
            raise ValueError("global_prompt must be a string no longer than 12000 characters")
        output_name = data.get("output_name", "final_video.mp4")
        if not isinstance(output_name, str) or not output_name or len(output_name) > 180:
            raise ValueError("output_name must be a filename of at most 180 characters")
        if output_name in {".", ".."} or _WINDOWS_UNSAFE_FILENAME.search(output_name) or output_name.endswith((" ", ".")):
            raise ValueError("output_name must be a safe filename, not a path")
        if not output_name.lower().endswith(".mp4"):
            raise ValueError("output_name must use the .mp4 extension")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        project_name = data.get("project_name", project_id)
        if not isinstance(project_name, str) or not project_name.strip() or len(project_name) > 160:
            raise ValueError("project_name must be a non-empty string no longer than 160 characters")
        return cls(
            project_id=project_id, scenes=scenes, initial_image=initial_image,
            global_prompt=global_prompt.strip(), output_name=output_name,
            metadata=metadata, schema_version=version, project_name=project_name.strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "project_name": self.project_name or self.project_id,
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
