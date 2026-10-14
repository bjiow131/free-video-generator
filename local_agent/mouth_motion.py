"""Simple prompt-derived mouth-motion cues for dialogue; no audio analysis or phoneme sync."""
from __future__ import annotations

from typing import Any


class MouthMotionError(ValueError):
    """Dialogue cannot be represented as safe mouth-motion cues."""


def compile_mouth_motion(
    scenes: list[dict[str, Any]],
    timeline: dict[str, Any],
    *,
    cycle_seconds: float = 0.32,
) -> dict[str, Any]:
    """Create coarse open/closed mouth cues for scenes containing dialogue.

    Dialogue timing is estimated from text length within the scene. This is
    deliberately not phoneme-level lip sync and does not require an audio file.
    The Blender adapter must map the cues to an existing mouth shape key or jaw
    control; this module never edits a Blender scene.
    """
    if not isinstance(scenes, list) or not isinstance(timeline, dict):
        raise MouthMotionError("scenes and timeline are required.")
    fps = timeline.get("fps")
    clips = timeline.get("clips")
    if isinstance(fps, bool) or not isinstance(fps, int) or fps < 1 or not isinstance(clips, list):
        raise MouthMotionError("timeline must contain a valid fps and clips list.")
    if isinstance(cycle_seconds, bool) or not isinstance(cycle_seconds, (int, float)) or not 0.1 <= cycle_seconds <= 1.0:
        raise MouthMotionError("cycle_seconds must be between 0.1 and 1.0.")
    clip_by_id = {clip.get("scene_id"): clip for clip in clips if isinstance(clip, dict)}
    cues = []
    warnings = []
    for scene in scenes:
        if not isinstance(scene, dict):
            raise MouthMotionError("Each scene must be an object.")
        dialogue = scene.get("dialogue", [])
        if not isinstance(dialogue, list):
            raise MouthMotionError("Scene dialogue must be a list.")
        if not dialogue:
            continue
        scene_id = scene.get("scene_id")
        clip = clip_by_id.get(scene_id)
        if clip is None:
            warnings.append({"scene_id": scene_id, "message": "No timeline clip found; mouth motion omitted."})
            continue
        valid_lines = []
        for line in dialogue:
            if not isinstance(line, dict) or not isinstance(line.get("speaker"), str) or not isinstance(line.get("text"), str):
                raise MouthMotionError("Dialogue lines require speaker and text strings.")
            speaker, text = line["speaker"].strip(), line["text"].strip()
            if speaker and text:
                valid_lines.append((speaker, text))
        if not valid_lines:
            continue
        start = clip["start_frame"]
        end = clip["end_frame"]
        total_frames = end - start + 1
        # Allocate scene dialogue time proportionally by text length, leaving a
        # small quiet margin at both ends when the scene is long enough.
        margin = min(int(round(0.15 * fps)), max(0, total_frames // 10))
        active_start, active_end = start + margin, end - margin
        available = max(1, active_end - active_start + 1)
        total_chars = sum(len(text) for _, text in valid_lines)
        cursor = active_start
        for index, (speaker, text) in enumerate(valid_lines):
            duration = available - (cursor - active_start) if index == len(valid_lines) - 1 else max(
                1, int(round(available * len(text) / max(1, total_chars)))
            )
            line_end = min(active_end, cursor + duration - 1)
            cycle_frames = max(2, int(round(float(cycle_seconds) * fps)))
            frame = cursor
            state_open = True
            while frame <= line_end:
                next_frame = min(line_end + 1, frame + max(1, cycle_frames // 2))
                cues.append({
                    "scene_id": scene_id,
                    "speaker": speaker,
                    "text": text,
                    "frame_start": frame,
                    "frame_end": next_frame - 1,
                    "mouth": "open" if state_open else "closed",
                    "execution_status": "planning_only",
                    "requires": "character_mouth_rig",
                })
                frame = next_frame
                state_open = not state_open
            cursor = line_end + 1
            if cursor > active_end:
                break
    return {
        "schema_version": 1,
        "method": "coarse_open_close",
        "audio_required": False,
        "phoneme_alignment": False,
        "cue_count": len(cues),
        "cues": cues,
        "warnings": warnings,
        "readiness": "planning_only",
        "execution_started": False,
    }
