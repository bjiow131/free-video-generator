"""Blender-independent camera path optimization.

Each frame supplies valid camera candidates (position tuples). The planner
minimizes travel and acceleration globally using second-order dynamic programming.
"""
from __future__ import annotations

import math
from typing import Sequence

Point = tuple[float, float, float]


def _distance2(a: Point, b: Point) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


def optimize_camera_path(
    candidates: Sequence[Sequence[Point]],
    *,
    movement_weight: float = 1.0,
    acceleration_weight: float = 4.0,
    reference_weight: float = 0.05,
) -> list[Point]:
    """Find the minimum-cost continuous path across all candidate frames.

    Candidate 0 is the preferred/original camera position at each frame.
    Invalid or nonfinite positions and empty candidate sets are rejected.
    """
    if not candidates:
        raise ValueError("camera timeline is empty")
    for weight in (movement_weight, acceleration_weight, reference_weight):
        if not math.isfinite(weight) or weight < 0:
            raise ValueError("camera path weights must be finite and nonnegative")
    frames: list[list[Point]] = []
    for frame, choices in enumerate(candidates, 1):
        if not choices:
            raise ValueError(f"no feasible camera position at frame {frame}")
        points = []
        for point in choices:
            if len(point) != 3 or not all(
                isinstance(v, (int, float)) and math.isfinite(v) for v in point
            ):
                raise ValueError(f"invalid camera candidate at frame {frame}")
            points.append(tuple(float(v) for v in point))
        frames.append(points)
    if len(frames) == 1:
        return [frames[0][0]]

    # State: (previous_index, current_index) -> (total_cost, index_path).
    states: dict[tuple[int, int], tuple[float, tuple[int, ...]]] = {}
    for i, a in enumerate(frames[0]):
        for j, b in enumerate(frames[1]):
            cost = movement_weight * _distance2(a, b)
            cost += reference_weight * (i != 0) + reference_weight * (j != 0)
            states[i, j] = (cost, (i, j))
    for t in range(2, len(frames)):
        next_states: dict[tuple[int, int], tuple[float, tuple[int, ...]]] = {}
        for (i, j), (cost, path) in states.items():
            a, b = frames[t - 2][i], frames[t - 1][j]
            for k, c in enumerate(frames[t]):
                acceleration = tuple(c[d] - 2 * b[d] + a[d] for d in range(3))
                step = movement_weight * _distance2(b, c)
                step += acceleration_weight * sum(v * v for v in acceleration)
                step += reference_weight * (k != 0)
                key = (j, k)
                proposal = (cost + step, path + (k,))
                if key not in next_states or proposal < next_states[key]:
                    next_states[key] = proposal
        states = next_states
    _, best = min(states.values())
    return [frames[t][index] for t, index in enumerate(best)]
