"""Deterministic, data-only multi-scene timeline scheduling.

This module creates frame ranges and transition overlaps; it does not launch
Blender, import assets, render, or execute scene instructions.
"""
from __future__ import annotations

from typing import Any

SUPPORTED_TRANSITIONS = frozenset({"cut", "crossfade", "dissolve"})


class TimelineError(ValueError):
    """A scene list cannot be represented as a safe timeline."""


def compile_timeline(scenes: list[dict[str, Any]], *, fps: int = 24,
                     transition_seconds: float = 0.5) -> dict[str, Any]:
    """Build contiguous inclusive frame ranges with bounded crossfade overlaps.

    Each scene's `transition` describes the transition OUT of that scene.
    Unknown transition names degrade safely to a cut and are reported.
    """
    if not isinstance(scenes, list) or not scenes or len(scenes) > 80:
        raise TimelineError("scenes must contain 1-80 entries.")
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 120:
        raise TimelineError("fps must be an integer from 1 to 120.")
    if isinstance(transition_seconds, bool) or not isinstance(transition_seconds, (int, float)):
        raise TimelineError("transition_seconds must be numeric.")
    if not 0 <= transition_seconds <= 5:
        raise TimelineError("transition_seconds must be between 0 and 5.")
    normalized = []
    warnings = []
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise TimelineError(f"scene {index + 1} must be an object.")
        seconds = scene.get("duration_seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= 120:
            raise TimelineError(f"scene {index + 1} duration_seconds must be an integer from 1 to 120.")
        scene_id = scene.get("scene_id", f"scene_{index + 1:03d}")
        if not isinstance(scene_id, str) or not scene_id:
            raise TimelineError(f"scene {index + 1} scene_id must be a non-empty string.")
        raw_transition = scene.get("transition", "cut")
        if not isinstance(raw_transition, str):
            raise TimelineError(f"scene {index + 1} transition must be a string.")
        transition = raw_transition.strip().lower().replace("-", "_").replace(" ", "_")
        if transition not in SUPPORTED_TRANSITIONS:
            warnings.append({
                "scene_id": scene_id,
                "message": f"Unsupported transition {raw_transition!r}; using cut.",
            })
            transition = "cut"
        normalized.append({
            "scene_id": scene_id,
            "title": str(scene.get("title", scene_id)),
            "duration_frames": max(1, int(round(seconds * fps))),
            "transition_out": transition,
        })

    overlaps = []
    for index, scene in enumerate(normalized):
        if index == len(normalized) - 1:
            if scene["transition_out"] != "cut":
                warnings.append({
                    "scene_id": scene["scene_id"],
                    "message": "Final scene has no following scene; outgoing transition ignored.",
                })
            overlaps.append(0)
            continue
        if scene["transition_out"] == "cut" or transition_seconds == 0:
            overlaps.append(0)
        else:
            requested = max(1, int(round(transition_seconds * fps)))
            overlaps.append(min(
                requested,
                max(1, scene["duration_frames"] // 2),
                max(1, normalized[index + 1]["duration_frames"] // 2),
            ))

    clips = []
    cursor = 1
    for index, scene in enumerate(normalized):
        start = cursor
        end = start + scene["duration_frames"] - 1
        clips.append({
            "scene_id": scene["scene_id"],
            "title": scene["title"],
            "start_frame": start,
            "end_frame": end,
            "duration_frames": scene["duration_frames"],
            "duration_seconds": round(scene["duration_frames"] / fps, 4),
            "transition_out": scene["transition_out"] if index < len(normalized) - 1 else "cut",
            "overlap_frames": overlaps[index],
        })
        if index < len(normalized) - 1:
            cursor = end + 1 - overlaps[index]
    total_frames = clips[-1]["end_frame"]
    return {
        "schema_version": 1,
        "fps": fps,
        "start_frame": 1,
        "end_frame": total_frames,
        "total_frames": total_frames,
        "total_duration_seconds": round(total_frames / fps, 4),
        "scene_count": len(clips),
        "transition_seconds_requested": transition_seconds,
        "clips": clips,
        "warnings": warnings,
        "readiness": "planning_only",
        "execution_started": False,
    }
