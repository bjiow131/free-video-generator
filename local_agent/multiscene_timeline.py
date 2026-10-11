"""Deterministic, Blender-independent timeline validation and compilation."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Segment:
    name: str
    seconds: float
    camera_dx: float = 0.0
    object_dx: float = 0.0


@dataclass(frozen=True)
class TimelineSegment:
    name: str
    start_frame: int
    end_frame: int
    camera_x: float
    object_x: float


def compile_timeline(segments: Sequence[Segment], *, fps: int = 12,
                     max_frames: int = 18000) -> list[TimelineSegment]:
    """Compile sequential segments with no frame gaps or overlaps.

    The positions are cumulative, so scene boundaries retain continuity.
    This function does not run Blender or render media.
    """
    if not isinstance(fps, int) or isinstance(fps, bool) or not 1 <= fps <= 120:
        raise ValueError("fps must be an integer from 1 to 120")
    if not isinstance(max_frames, int) or isinstance(max_frames, bool) or max_frames < 1:
        raise ValueError("max_frames must be positive")
    if not segments:
        raise ValueError("at least one segment is required")
    result: list[TimelineSegment] = []
    cursor = 1
    camera_x = object_x = 0.0
    for segment in segments:
        if not isinstance(segment, Segment):
            raise TypeError("each segment must be a Segment")
        if not isinstance(segment.name, str) or not segment.name.strip():
            raise ValueError("segment name is required")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   and math.isfinite(v) for v in
                   (segment.seconds, segment.camera_dx, segment.object_dx)):
            raise ValueError("segment values must be finite numbers")
        if segment.seconds <= 0:
            raise ValueError("segment duration must be positive")
        frames = round(segment.seconds * fps)
        if frames < 1:
            raise ValueError("segment duration is shorter than one frame")
        if cursor + frames - 1 > max_frames:
            raise ValueError("timeline exceeds max_frames")
        camera_x += segment.camera_dx
        object_x += segment.object_dx
        result.append(TimelineSegment(segment.name, cursor, cursor + frames - 1,
                                      camera_x, object_x))
        cursor += frames
    return result
