"""Local, reviewable extraction of silhouette targets from character references.

The analyzer never uploads images. It prefers an existing alpha channel; for
opaque images it estimates a flat background from the image border and refuses
ambiguous masks. Every mask is written for visual review before fitting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Iterable

import numpy as np
from PIL import Image
from scipy import ndimage

from .reference_to_model import parse_spec

_VIEW_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")


class ReferenceImageError(ValueError):
    """Raised when an image cannot safely produce a usable silhouette map."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_mask(mask: np.ndarray) -> np.ndarray:
    labels, count = ndimage.label(mask)
    if count == 0:
        raise ReferenceImageError("foreground_not_found")
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    # Keep multiple meaningful islands (hair tips, bag straps, loose garments)
    # while removing isolated border-noise pixels.
    minimum = max(4, int(mask.size * 0.0001))
    keep = np.flatnonzero(sizes >= minimum)
    keep = keep[keep != 0]
    result = np.isin(labels, keep)
    ratio = float(result.mean())
    if ratio < 0.005 or ratio > 0.92:
        raise ReferenceImageError("foreground_area_implausible")
    return result


def _foreground(image: Image.Image, background_tolerance: float) -> tuple[np.ndarray, str]:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    alpha = rgba[:, :, 3]
    if np.any(alpha < 250):
        return _clean_mask(alpha >= 16), "alpha_channel"

    rgb = rgba[:, :, :3].astype(np.float32) / 255.0
    h, w, _ = rgb.shape
    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]), axis=0)
    background = np.median(border, axis=0)
    distance = np.sqrt(np.sum((rgb - background) ** 2, axis=2))
    border_distance = np.sqrt(np.sum((border - background) ** 2, axis=1))
    # A border that is not close to one color is not a reliable flat background.
    if float(np.quantile(border_distance, 0.9)) > max(background_tolerance * 1.5, 0.08):
        raise ReferenceImageError("background_not_uniform; supply_alpha_or_mask")
    mask = distance > background_tolerance
    # Close small gaps before rejecting tiny disconnected image noise.
    mask = ndimage.binary_closing(mask, structure=np.ones((3, 3), dtype=bool))
    return _clean_mask(mask), "estimated_flat_border"


def _contour_samples(mask: np.ndarray, sample_count: int) -> list[list[float]]:
    boundary = mask & ~ndimage.binary_erosion(mask, structure=np.ones((3, 3), dtype=bool))
    ys, xs = np.nonzero(boundary)
    if len(xs) < sample_count:
        raise ReferenceImageError("silhouette_boundary_too_small")
    cx, cy = float(xs.mean()), float(ys.mean())
    angles = np.arctan2(ys - cy, xs - cx)
    order = np.argsort(angles, kind="stable")
    ordered_x, ordered_y = xs[order], ys[order]
    indices = np.linspace(0, len(ordered_x) - 1, sample_count, dtype=int)
    h, w = mask.shape
    # Blender camera coordinates use bottom-left origin; image arrays use top-left.
    return [[float(ordered_x[i] / max(w - 1, 1)),
             float(1.0 - ordered_y[i] / max(h - 1, 1))] for i in indices]


def analyze_views(views: Iterable[tuple[str, str | Path]], output_dir: str | Path,
                  *, sample_count: int = 128, background_tolerance: float = 0.12) -> dict:
    """Build a hash-pinned schema-v1 silhouette map from named view images.

    ``views`` is a sequence of ``(view_name, image_path)`` pairs. Camera names
    default to ``CAM_<VIEW>`` and must be created/calibrated by the Blender stage.
    The returned map is input for fitting, not proof that its segmentation is
    correct; inspect the emitted mask PNGs before authorizing a fit.
    """
    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or not 16 <= sample_count <= 512:
        raise ReferenceImageError("sample_count_must_be_between_16_and_512")
    if not isinstance(background_tolerance, (int, float)) or not 0.01 <= background_tolerance <= 0.5:
        raise ReferenceImageError("background_tolerance_out_of_bounds")
    pairs = list(views)
    if not pairs:
        raise ReferenceImageError("at_least_one_view_required")
    names = set()
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    image_hashes = []
    mapped_views = []
    for name, raw_path in pairs:
        if not isinstance(name, str) or not _VIEW_RE.fullmatch(name) or name in names:
            raise ReferenceImageError("invalid_or_duplicate_view_name")
        names.add(name)
        path = Path(raw_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ReferenceImageError("reference_image_not_a_file")
        try:
            with Image.open(path) as opened:
                image = opened.copy()
        except (OSError, ValueError) as exc:
            raise ReferenceImageError("reference_image_unreadable") from exc
        if image.width < 32 or image.height < 32:
            raise ReferenceImageError("reference_image_too_small")
        mask, method = _foreground(image, float(background_tolerance))
        mask_name = f"mask_{name}.png"
        mask_path = root / mask_name
        if mask_path.exists() or mask_path.is_symlink():
            raise ReferenceImageError(f"mask_output_exists_no_overwrite:{mask_name}")
        Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(mask_path)
        ys, xs = np.nonzero(mask)
        image_digest = sha256_file(path)
        image_hashes.append((name, image_digest))
        mapped_views.append({
            "name": name,
            "camera_name": f"CAM_{name.upper()}",
            "landmarks": [],
            "silhouette": _contour_samples(mask, sample_count),
            "analysis": {
                "source_basename": path.name,
                "source_sha256": image_digest,
                "width": image.width,
                "height": image.height,
                "mask_file": mask_name,
                "segmentation_method": method,
                "foreground_fraction": float(mask.mean()),
                "bounds_pixels": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
                "requires_mask_review": True,
            },
        })
    canonical = json.dumps(image_hashes, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    reference_digest = hashlib.sha256(canonical).hexdigest()
    spec = {
        "schema_version": 1,
        "character_name": "Character",
        "coordinate_convention": "camera_frame_bottom_left_normalized",
        "reference_sha256": reference_digest,
        "views": mapped_views,
        "controls": [],
    }
    parse_spec(spec, expected_sha256=reference_digest)
    result_path = root / "reference_map.json"
    if result_path.exists() or result_path.is_symlink():
        raise ReferenceImageError("reference_map_output_exists_no_overwrite")
    result_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "ready_for_review", "reference_map_file": str(result_path),
            "reference_sha256": reference_digest, "view_count": len(mapped_views),
            "views": [{"name": v["name"], "mask_file": v["analysis"]["mask_file"],
                       "segmentation_method": v["analysis"]["segmentation_method"],
                       "requires_mask_review": True} for v in mapped_views],
            "fit_ready": False,
            "next_gate": "review_masks_and_calibrate_matching_blender_cameras_add_controls"}


def _parse_view_arg(value: str) -> tuple[str, str]:
    name, sep, path = value.partition("=")
    if not sep or not path:
        raise argparse.ArgumentTypeError("view must have the form NAME=IMAGE_PATH")
    return name, path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", action="append", type=_parse_view_arg, required=True,
                        help="named source image, e.g. --view front=front.png (repeat for more views)")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--samples", type=int, default=128)
    parser.add_argument("--background-tolerance", type=float, default=0.12)
    args = parser.parse_args(argv)
    try:
        result = analyze_views(args.view, args.output_dir, sample_count=args.samples,
                               background_tolerance=args.background_tolerance)
    except (ReferenceImageError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
