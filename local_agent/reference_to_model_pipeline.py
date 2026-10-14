"""Run the local, donor-independent first Reference-to-Model draft."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Mapping, Sequence

from .reference_image_analyzer import analyze_views
from .visual_hull import VisualHullError, build_visual_hull

_VIEW_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
_OBJ_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\.obj$")


class FirstRunError(ValueError):
    """Raised when the reference set cannot form a calibrated first draft."""


def run_first_draft(views: Sequence[Mapping[str, object]], world_bounds: Mapping[str, Sequence[float]],
                    output_dir: str | Path, *, obj_name: str = "reference_hull.obj",
                    grid_size: int = 64, sample_count: int = 128) -> dict:
    """Create reviewed image masks, a pinned map, and a coarse OBJ visual hull.

    Each view requires an image path and explicit orthographic axis mapping.
    The result is a geometry draft for review, not production topology or a rig.
    """
    if not isinstance(views, (list, tuple)) or len(views) < 2:
        raise FirstRunError("at_least_two_reference_views_required")
    if not isinstance(obj_name, str) or not _OBJ_NAME.fullmatch(obj_name):
        raise FirstRunError("obj_name_must_be_a_safe_obj_filename")
    names: set[str] = set()
    analyzer_views = []
    hull_views = []
    for view in views:
        if not isinstance(view, Mapping):
            raise FirstRunError("view_must_be_an_object")
        name, image_path = view.get("name"), view.get("image_path")
        horizontal, vertical = view.get("horizontal_axis"), view.get("vertical_axis")
        if not isinstance(name, str) or not _VIEW_NAME.fullmatch(name) or name in names:
            raise FirstRunError("view_name_invalid_or_duplicate")
        if not isinstance(image_path, (str, Path)) or not str(image_path):
            raise FirstRunError("view_image_path_required")
        if horizontal not in {"x", "y", "z"} or vertical not in {"x", "y", "z"} or horizontal == vertical:
            raise FirstRunError("view_requires_two_distinct_world_axes")
        names.add(name)
        analyzer_views.append((name, image_path))
        item = {"name": name, "horizontal_axis": horizontal, "vertical_axis": vertical}
        item["mask_path"] = ""  # replaced after the analyzer writes review masks
        for key in ("horizontal_sign", "vertical_sign"):
            if key in view:
                item[key] = view[key]
        hull_views.append(item)
    used_axes = {axis for view in hull_views for axis in (view["horizontal_axis"], view["vertical_axis"])}
    if used_axes != {"x", "y", "z"}:
        raise FirstRunError("views_must_cover_all_three_world_axes")

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    analysis_dir = root / "reference_analysis"
    analysis = analyze_views(analyzer_views, analysis_dir, sample_count=sample_count)
    for view in hull_views:
        view["mask_path"] = str(analysis_dir / f"mask_{view['name']}.png")
    output_obj = root / obj_name
    try:
        hull = build_visual_hull(hull_views, world_bounds, output_obj, grid_size=grid_size)
    except (VisualHullError, OSError) as exc:
        return {"status": "blocked", "reason": str(exc), "reference_map_file": analysis["reference_map_file"],
                "mask_review_required": True, "fit_ready": False, "production_ready": False}
    return {"status": "draft_ready_for_review", "reference_map_file": analysis["reference_map_file"],
            "reference_sha256": analysis["reference_sha256"], "mask_files": [
                str(analysis_dir / f"mask_{view['name']}.png") for view in views],
            "mesh_file": hull["mesh_file"], "mesh_quality": hull["quality"],
            "occupied_voxels": hull["occupied_voxels"], "surface_faces": hull["surface_faces"],
            "mask_review_required": True, "fit_ready": False, "production_ready": False,
            "next_gate": "review_masks_calibrate_cameras_add_semantic_landmarks_retopologize_and_test_rig"}


def _parse_view(value: str) -> dict:
    name, separator, data = value.partition("=")
    fields = data.split(",")
    if not separator or len(fields) not in (3, 5):
        raise argparse.ArgumentTypeError("view must be NAME=IMAGE,HORIZONTAL_AXIS,VERTICAL_AXIS[,H_SIGN,V_SIGN]")
    view = {"name": name, "image_path": fields[0], "horizontal_axis": fields[1], "vertical_axis": fields[2]}
    if len(fields) == 5:
        try:
            view["horizontal_sign"], view["vertical_sign"] = int(fields[3]), int(fields[4])
        except ValueError as exc:
            raise argparse.ArgumentTypeError("view signs must be -1 or 1") from exc
    return view


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", action="append", type=_parse_view, required=True)
    for axis in "xyz":
        parser.add_argument(f"--bounds-{axis}", nargs=2, type=float, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--obj-name", default="reference_hull.obj")
    parser.add_argument("--grid-size", type=int, default=64)
    parser.add_argument("--sample-count", type=int, default=128)
    args = parser.parse_args(argv)
    bounds = {axis: getattr(args, f"bounds_{axis}") for axis in "xyz"}
    try:
        result = run_first_draft(args.view, bounds, args.output_dir, obj_name=args.obj_name,
                                 grid_size=args.grid_size, sample_count=args.sample_count)
    except (FirstRunError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "draft_ready_for_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
