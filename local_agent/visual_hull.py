"""Build a donor-independent orthographic visual-hull OBJ from reviewed masks.

This is a coarse starting mesh, not a finished, retopologized or rigged
character. It requires explicit world bounds and calibrated orthographic views.
"""
from __future__ import annotations

from pathlib import Path
import re

import numpy as np
from PIL import Image

_AXES = {"x": 0, "y": 1, "z": 2}
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}[.]obj$")


class VisualHullError(ValueError):
    pass


def _valid_range(value) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise VisualHullError("world_range_must_have_two_values")
    lo, hi = value
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and np.isfinite(x) for x in value) or hi <= lo:
        raise VisualHullError("world_range_invalid")
    return float(lo), float(hi)


def _face_corners(i: int, j: int, k: int, axis: int, positive: bool) -> tuple[tuple[int, int, int], ...]:
    if axis == 0 and positive:
        return ((i+1,j,k),(i+1,j+1,k),(i+1,j+1,k+1),(i+1,j,k+1))
    if axis == 0:
        return ((i,j,k),(i,j,k+1),(i,j+1,k+1),(i,j+1,k))
    if axis == 1 and positive:
        return ((i,j+1,k),(i,j+1,k+1),(i+1,j+1,k+1),(i+1,j+1,k))
    if axis == 1:
        return ((i,j,k),(i+1,j,k),(i+1,j,k+1),(i,j,k+1))
    if positive:
        return ((i,j,k+1),(i+1,j,k+1),(i+1,j+1,k+1),(i,j+1,k+1))
    return ((i,j,k),(i,j+1,k),(i+1,j+1,k),(i+1,j,k))


def build_visual_hull(mask_views: list[dict], world_bounds: dict, output_obj: str | Path,
                      *, grid_size: int = 64) -> dict:
    """Carve a calibrated orthographic visual hull and write an indexed OBJ.

    Each view has ``name``, ``mask_path``, ``horizontal_axis`` and
    ``vertical_axis`` (distinct x/y/z values), plus optional signs of +/-1.
    World bounds are ``{"x": [min,max], "y": [min,max], "z": [min,max]}``.
    Image masks should be reviewed outputs from the reference analyzer.
    """
    if not isinstance(grid_size, int) or isinstance(grid_size, bool) or not 16 <= grid_size <= 128:
        raise VisualHullError("grid_size_must_be_between_16_and_128")
    if not isinstance(mask_views, list) or len(mask_views) < 2:
        raise VisualHullError("at_least_two_calibrated_views_required")
    if not isinstance(world_bounds, dict) or set(world_bounds) != {"x", "y", "z"}:
        raise VisualHullError("world_bounds_must_define_x_y_z")
    bounds = [_valid_range(world_bounds[a]) for a in ("x", "y", "z")]
    arrays = np.meshgrid(*[np.linspace(lo+(hi-lo)/(2*grid_size), hi-(hi-lo)/(2*grid_size), grid_size)
                           for lo, hi in bounds], indexing="ij")
    points = np.stack(arrays, axis=-1).reshape(-1, 3)
    occupied = np.ones(len(points), dtype=bool)
    seen = set()
    for view in mask_views:
        if not isinstance(view, dict) or not isinstance(view.get("name"), str) or view["name"] in seen:
            raise VisualHullError("view_name_invalid_or_duplicate")
        seen.add(view["name"])
        horizontal, vertical = view.get("horizontal_axis"), view.get("vertical_axis")
        if horizontal not in _AXES or vertical not in _AXES or horizontal == vertical:
            raise VisualHullError("view_axes_must_be_distinct_x_y_z")
        hs, vs = view.get("horizontal_sign", 1), view.get("vertical_sign", 1)
        if hs not in (-1, 1) or vs not in (-1, 1):
            raise VisualHullError("view_signs_must_be_plus_or_minus_one")
        mask_path = Path(view.get("mask_path", "")).expanduser().resolve(strict=True)
        if not mask_path.is_file():
            raise VisualHullError("mask_path_not_a_file")
        try:
            with Image.open(mask_path) as image:
                mask = np.asarray(image.convert("L"), dtype=np.uint8) >= 128
        except (OSError, ValueError) as exc:
            raise VisualHullError("mask_unreadable") from exc
        h, w = mask.shape
        if min(h, w) < 16 or mask.mean() < 0.005 or mask.mean() > 0.92:
            raise VisualHullError("mask_dimensions_or_coverage_invalid")
        for axis, sign in ((_AXES[horizontal], hs), (_AXES[vertical], vs)):
            lo, hi = bounds[axis]
            normalized = (points[:, axis] - lo) / (hi - lo)
            if sign < 0:
                normalized = 1.0 - normalized
            if axis == _AXES[horizontal]:
                u = normalized
            else:
                v = normalized
        px = np.clip(np.rint(u * (w - 1)).astype(np.int32), 0, w - 1)
        py = np.clip(np.rint((1.0 - v) * (h - 1)).astype(np.int32), 0, h - 1)
        occupied &= mask[py, px]
        if not occupied.any():
            raise VisualHullError("calibrated_masks_have_empty_intersection")
    volume = occupied.reshape((grid_size, grid_size, grid_size))
    if int(volume.sum()) < 8:
        raise VisualHullError("visual_hull_too_small")

    def exposed(axis: int, positive: bool) -> np.ndarray:
        neighbor = np.zeros_like(volume)
        src = [slice(None)] * 3
        dst = [slice(None)] * 3
        if positive:
            src[axis] = slice(0, -1); dst[axis] = slice(1, None)
        else:
            src[axis] = slice(1, None); dst[axis] = slice(0, -1)
        neighbor[tuple(src)] = volume[tuple(dst)]
        return volume & ~neighbor

    obj_path = Path(output_obj).expanduser().resolve()
    if not _SAFE.fullmatch(obj_path.name):
        raise VisualHullError("output_must_be_a_safe_obj_basename")
    if obj_path.exists() or obj_path.is_symlink():
        raise VisualHullError("output_exists_no_overwrite")
    obj_path.parent.mkdir(parents=True, exist_ok=True)
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    vertex_ids: dict[tuple[int, int, int], int] = {}
    cell_steps = [(hi-lo)/grid_size for lo, hi in bounds]
    mins = [lo for lo, _ in bounds]
    face_count = 0
    for axis in range(3):
        for positive in (False, True):
            cells = np.argwhere(exposed(axis, positive))
            face_count += len(cells)
            for i, j, k in cells:
                quad = []
                for corner in _face_corners(int(i), int(j), int(k), axis, positive):
                    if corner not in vertex_ids:
                        vertex_ids[corner] = len(vertices) + 1
                        vertices.append(tuple(mins[a] + corner[a] * cell_steps[a] for a in range(3)))
                    quad.append(vertex_ids[corner])
                faces.append(tuple(quad))
    with obj_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("# Calibrated orthographic visual hull; review before production use\n")
        stream.write("o ReferenceVisualHull\n")
        for xyz in vertices:
            stream.write("v %.7f %.7f %.7f\n" % xyz)
        for face in faces:
            stream.write("f %d %d %d %d\n" % face)
    return {"status": "completed", "mesh_file": str(obj_path), "mesh_format": "OBJ",
            "grid_size": grid_size, "occupied_voxels": int(volume.sum()),
            "surface_faces": face_count, "vertex_count": len(vertices),
            "quality": "coarse_visual_hull", "production_ready": False,
            "next_gate": "inspect_smoothing_retopology_face_clothing_and_animation"}
