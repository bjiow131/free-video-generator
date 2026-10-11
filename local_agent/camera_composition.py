"""Pure-Python camera framing calculations used by Blender's rendering script."""
from __future__ import annotations

import math


def preferred_focal_length(
    fitting_lens: float,
    projected_height: float,
    *,
    target_fraction: float = 0.38,
    max_lens: float = 100.0,
) -> float:
    """Zoom toward a useful subject size without exceeding the lens limit.

    The caller must recheck framing and occlusion using the returned lens.
    When zoom is impossible, the fitted lens is preserved.
    """
    for name, value in (
        ("fitting_lens", fitting_lens),
        ("projected_height", projected_height),
        ("target_fraction", target_fraction),
        ("max_lens", max_lens),
    ):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if fitting_lens <= 0 or max_lens < fitting_lens:
        raise ValueError("invalid lens limits")
    if projected_height < 0 or not 0 < target_fraction < 1:
        raise ValueError("invalid framing proportions")
    if projected_height <= 1e-5 or projected_height >= target_fraction:
        return float(fitting_lens)
    return float(min(max_lens, fitting_lens * target_fraction / projected_height))
