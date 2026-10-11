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
    initialize_closed: bool = True,
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
    keyframes = [{"frame": frame_start, "mouth_state": "closed"}] if initialize_closed else []
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


def apply_dialogue_cues(
    cues: Any,
    *,
    character_objects_by_speaker: dict[str, Iterable[Any]],
    frame_start: int,
    frame_end: int,
) -> dict[str, Any]:
    """Apply each cue only to the explicitly mapped speaker's character objects.

    A missing speaker mapping is reported rather than falling back to another
    character in the scene. The mapping must be built from trusted project asset
    IDs, not from free-form prompt text.
    """
    if not isinstance(cues, list):
        return {"status": "rejected", "reason": "cues_must_be_a_list", "results": []}
    if not isinstance(character_objects_by_speaker, dict):
        return {
            "status": "rejected",
            "reason": "speaker_object_mapping_required",
            "results": [],
        }

    # Validate the complete batch before touching any rig. A malformed later
    # cue must not leave earlier characters partially animated.
    normalized_cues = [
        validate_dialogue_cue(cue, frame_start=frame_start, frame_end=frame_end)
        for cue in cues
    ]
    seen_line_ids: set[str] = set()
    for normalized in normalized_cues:
        line_id = normalized["line_id"]
        if line_id in seen_line_ids:
            return {
                "status": "rejected",
                "reason": "duplicate_line_id",
                "line_id": line_id,
                "results": [],
            }
        seen_line_ids.add(line_id)

    # Materialize iterables once: multiple lines must address the same meshes.
    objects_by_speaker = {
        speaker: list(objects) for speaker, objects in character_objects_by_speaker.items()
    }
    initialized: set[str] = set()
    results: list[dict[str, Any]] = []
    for normalized in sorted(normalized_cues, key=lambda item: item["events"][0]["frame"]):
        line_id = normalized["line_id"]
        speaker_id = normalized["speaker_id"]
        if speaker_id not in character_objects_by_speaker:
            results.append({
                "status": "speaker_asset_not_found",
                "speaker_id": speaker_id,
                "line_id": line_id,
                "applied_events": 0,
            })
            continue
        result = apply_mouth_cue(
            normalized,
            character_objects=objects_by_speaker[speaker_id],
            initialize_closed=speaker_id not in initialized,
            frame_start=frame_start,
            frame_end=frame_end,
        )
        if result["status"] == "applied":
            initialized.add(speaker_id)
        results.append(result)

    statuses = {item["status"] for item in results}
    if not results:
        status = "no_cues"
    elif statuses == {"applied"}:
        status = "applied"
    elif "applied" in statuses:
        status = "partial"
    else:
        status = "unsupported"
    return {"status": status, "results": results}


def index_character_objects_by_speaker(
    objects: Iterable[Any],
    *,
    id_property: str = "local_agent_character_id",
) -> dict[str, Any]:
    """Index Blender objects only by an explicit stable character-ID property.

    No object-name guessing is allowed: all mesh parts of one character may
    carry the same property value and are grouped for shape-key discovery.
    """
    import re

    if not isinstance(id_property, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", id_property):
        return {"status": "rejected", "reason": "invalid_id_property", "characters": {}, "unindexed_objects": []}

    characters: dict[str, list[Any]] = {}
    unindexed: list[str] = []
    invalid: list[str] = []
    for obj in objects:
        name = str(getattr(obj, "name", ""))
        getter = getattr(obj, "get", None)
        character_id = getter(id_property) if callable(getter) else None
        if not isinstance(character_id, str) or not re.fullmatch(r"char\.[a-z0-9_.-]{1,100}", character_id):
            unindexed.append(name)
            continue
        if getattr(obj, "type", "MESH") != "MESH":
            invalid.append(name)
            continue
        characters.setdefault(character_id, []).append(obj)

    return {
        "status": "indexed",
        "id_property": id_property,
        "characters": characters,
        "character_count": len(characters),
        "indexed_object_count": sum(len(items) for items in characters.values()),
        "unindexed_objects": unindexed,
        "non_mesh_objects": invalid,
    }
