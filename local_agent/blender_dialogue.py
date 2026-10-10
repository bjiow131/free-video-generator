"""Apply simple open/closed mouth cues to verified Blender shape keys.

This adapter deliberately does not guess at jaw-bone axes. If a compatible
shape key is not found on the supplied character meshes, it reports an
unsupported control instead of claiming the animation was applied.
"""
from __future__ import annotations

from typing import Any, Iterable

from .dialogue_cues import validate_dialogue_cue

_MOUTH_KEY_NAMES = {
    "mouthopen",
    "openmouth",
    "mouth_open",
    "mouth-open",
    "jawopen",
    "jaw_open",
    "jaw-open",
}


def _find_mouth_shape_key(character_objects: Iterable[Any]) -> tuple[Any, Any] | None:
    for obj in character_objects:
        data = getattr(obj, "data", None)
        shape_keys = getattr(data, "shape_keys", None)
        key_blocks = getattr(shape_keys, "key_blocks", None)
        if key_blocks is None:
            continue
        try:
            blocks = list(key_blocks)
        except TypeError:
            continue
        for block in blocks:
            name = getattr(block, "name", "")
            normalized = str(name).strip().lower().replace(" ", "")
            if normalized in _MOUTH_KEY_NAMES:
                return obj, block
    return None


def apply_mouth_cue(
    cue: dict[str, Any],
    *,
    character_objects: Iterable[Any],
    frame_start: int,
    frame_end: int,
) -> dict[str, Any]:
    """Keyframe a supported mouth-open shape key; return an explicit result.

    The cue must be prevalidated against the shot frame range. The supplied
    character objects must already be resolved from trusted project IDs.
    """
    normalized = validate_dialogue_cue(
        cue, frame_start=frame_start, frame_end=frame_end
    )
    found = _find_mouth_shape_key(character_objects)
    if found is None:
        return {
            "status": "unsupported_rig_control",
            "speaker_id": normalized["speaker_id"],
            "line_id": normalized["line_id"],
            "control": "mouth_open_shape_key",
            "applied_events": 0,
        }

    obj, shape_key = found
    # Establish a closed mouth at shot start, then apply the estimated or
    # audio-confirmed open/closed events. The metadata status is preserved.
    keyframes = [{"frame": frame_start, "mouth_state": "closed"}]
    keyframes.extend(normalized["events"])
    collapsed: list[dict[str, Any]] = []
    for event in keyframes:
        if collapsed and collapsed[-1]["frame"] == event["frame"]:
            collapsed[-1] = event
        elif collapsed and collapsed[-1]["mouth_state"] == event["mouth_state"]:
            continue
        else:
            collapsed.append(event)

    for event in collapsed:
        shape_key.value = 1.0 if event["mouth_state"] == "open" else 0.0
        shape_key.keyframe_insert(data_path="value", frame=event["frame"])

    return {
        "status": "applied",
        "speaker_id": normalized["speaker_id"],
        "line_id": normalized["line_id"],
        "object": getattr(obj, "name", ""),
        "shape_key": getattr(shape_key, "name", ""),
        "applied_events": len(collapsed),
        "timing_status": normalized["timing_status"],
        "control": "shape_key",
    }
