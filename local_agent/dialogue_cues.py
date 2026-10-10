"""Validate simple script-based mouth cues without claiming phoneme-level sync."""
from __future__ import annotations

import re
from typing import Any

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_STATES = {"open", "closed"}
_TIMING_STATUSES = {"estimated_until_voiceover", "confirmed_from_audio"}


class DialogueCueError(ValueError):
    """A dialogue cue is malformed or falls outside its shot."""


def validate_dialogue_cue(
    data: Any,
    *,
    frame_start: int,
    frame_end: int,
) -> dict[str, Any]:
    """Return a normalized cue after strict schema and frame-range validation.

    This validates metadata only. It does not animate a Blender rig, verify an
    audio track, or prove that timing is synchronized to recorded speech.
    """
    if isinstance(frame_start, bool) or not isinstance(frame_start, int):
        raise DialogueCueError("frame_start must be an integer.")
    if isinstance(frame_end, bool) or not isinstance(frame_end, int):
        raise DialogueCueError("frame_end must be an integer.")
    if frame_end < frame_start:
        raise DialogueCueError("frame_end must be greater than or equal to frame_start.")
    if not isinstance(data, dict):
        raise DialogueCueError("Dialogue cue must be an object.")
    allowed = {"speaker_id", "line_id", "text", "timing_status", "events"}
    if set(data) - allowed:
        raise DialogueCueError("Dialogue cue contains unsupported fields.")

    def identifier(key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not _ID_RE.fullmatch(value):
            raise DialogueCueError(f"{key} must be a stable identifier.")
        return value

    speaker_id = identifier("speaker_id")
    line_id = identifier("line_id")
    text = data.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 700:
        raise DialogueCueError("text must be a non-empty string of at most 700 characters.")

    timing_status = data.get("timing_status")
    if timing_status not in _TIMING_STATUSES:
        raise DialogueCueError("timing_status must be estimated_until_voiceover or confirmed_from_audio.")

    raw_events = data.get("events")
    if not isinstance(raw_events, list) or not 1 <= len(raw_events) <= 500:
        raise DialogueCueError("events must contain 1-500 mouth-state events.")

    events: list[dict[str, Any]] = []
    previous_frame: int | None = None
    previous_state: str | None = None
    for index, event in enumerate(raw_events, start=1):
        if not isinstance(event, dict) or set(event) != {"frame", "mouth_state"}:
            raise DialogueCueError(f"Event {index} must contain only frame and mouth_state.")
        frame = event.get("frame")
        state = event.get("mouth_state")
        if isinstance(frame, bool) or not isinstance(frame, int):
            raise DialogueCueError(f"Event {index} frame must be an integer.")
        if not frame_start <= frame <= frame_end:
            raise DialogueCueError(f"Event {index} frame is outside the shot range.")
        if previous_frame is not None and frame <= previous_frame:
            raise DialogueCueError("Event frames must be strictly increasing.")
        if state not in _STATES:
            raise DialogueCueError(f"Event {index} mouth_state must be open or closed.")
        if state == previous_state:
            raise DialogueCueError("Adjacent duplicate mouth states must be collapsed.")
        events.append({"frame": frame, "mouth_state": state})
        previous_frame, previous_state = frame, state

    return {
        "speaker_id": speaker_id,
        "line_id": line_id,
        "text": text.strip(),
        "timing_status": timing_status,
        "events": events,
    }
