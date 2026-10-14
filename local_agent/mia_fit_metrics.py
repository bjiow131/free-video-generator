"""Deterministic acceptance gate for Mia reference fitting.

Consumes landmark/segmentation measurements produced by a separate calibrated
image analyzer; it does NOT extract features or edit Blender meshes by itself.
Only compares aligned images from the same approved camera and reference version.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Mapping, Sequence

_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
REGION_WEIGHTS = {"silhouette": 4.0, "face": 5.0, "hair": 5.0, "eyes": 5.0,
                  "clothes": 1.5, "backpack": 1.0, "boots": 1.0}


class FitEvidenceError(ValueError):
    """Evidence is missing, mismatched, unaligned, or not measurable."""


@dataclass(frozen=True)
class MeasuredView:
    view: str
    camera_id: str
    width: int
    height: int
    regions: Mapping[str, bytes]
    landmarks: Mapping[str, tuple[float, float]]


@dataclass(frozen=True)
class FitCandidate:
    candidate_id: str
    source_geometry_sha256: str
    geometry_sha256: str
    render_sha256: Mapping[str, str]
    views: Mapping[str, MeasuredView]


def _check_view(view: MeasuredView) -> None:
    if view.width < 16 or view.height < 16 or view.width > 4096 or view.height > 4096:
        raise FitEvidenceError("Invalid image dimensions")
    if not view.camera_id.strip():
        raise FitEvidenceError("Camera calibration missing")
    if "silhouette" not in view.regions:
        raise FitEvidenceError("Silhouette mask missing")
    for name, mask in view.regions.items():
        if name not in REGION_WEIGHTS or not isinstance(mask, bytes) or len(mask) != view.width * view.height:
            raise FitEvidenceError("Invalid binary region mask")
        if any(pixel not in (0, 1) for pixel in mask):
            raise FitEvidenceError("Region mask must be binary")
    for name, point in view.landmarks.items():
        if not isinstance(name, str) or len(point) != 2 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in point):
            raise FitEvidenceError("Invalid normalized landmark")


def mask_iou(left: bytes, right: bytes) -> float:
    if len(left) != len(right) or not left:
        raise FitEvidenceError("Masks have incompatible dimensions")
    union = sum(bool(a or b) for a, b in zip(left, right))
    if union == 0:
        raise FitEvidenceError("Cannot score two empty masks")
    return sum(bool(a and b) for a, b in zip(left, right)) / union


def view_loss(reference: MeasuredView, candidate: MeasuredView) -> float:
    _check_view(reference)
    _check_view(candidate)
    if (reference.view, reference.camera_id, reference.width, reference.height) != (candidate.view, candidate.camera_id, candidate.width, candidate.height):
        raise FitEvidenceError("Reference and candidate cameras or dimensions differ")
    if set(reference.regions) != set(candidate.regions) or set(reference.landmarks) != set(candidate.landmarks):
        raise FitEvidenceError("Missing image features: no imputation allowed")
    weighted_loss = 0.0
    weight = 0.0
    for region, ref_mask in reference.regions.items():
        w = REGION_WEIGHTS[region]
        weighted_loss += w * (1.0 - mask_iou(ref_mask, candidate.regions[region]))
        weight += w
    for landmark, ref_point in reference.landmarks.items():
        cur = candidate.landmarks[landmark]
        # Maximum distance between two normalized image points is sqrt(2).
        error = math.hypot(ref_point[0] - cur[0], ref_point[1] - cur[1]) / math.sqrt(2)
        w = 3.0 if any(label in landmark.lower() for label in ("eye", "nose", "mouth", "chin", "jaw")) else 1.0
        weighted_loss += w * error
        weight += w
    return weighted_loss / weight


def candidate_loss(reference: Mapping[str, MeasuredView], candidate: FitCandidate, required_views: Sequence[str]) -> float:
    if not required_views or len(set(required_views)) != len(required_views):
        raise FitEvidenceError("Required camera list must be nonempty and unique")
    if set(required_views) != set(reference) or set(required_views) != set(candidate.views) or set(required_views) != set(candidate.render_sha256):
        raise FitEvidenceError("Every required view must be measured")
    if not _SHA256.fullmatch(candidate.source_geometry_sha256) or not _SHA256.fullmatch(candidate.geometry_sha256):
        raise FitEvidenceError("Geometry SHA256 missing")
    if any(not _SHA256.fullmatch(digest) for digest in candidate.render_sha256.values()):
        raise FitEvidenceError("Image SHA256 missing")
    return sum(view_loss(reference[name], candidate.views[name]) for name in required_views) / len(required_views)


def decide_improvement(reference: Mapping[str, MeasuredView], previous: FitCandidate, proposed: FitCandidate,
                       required_views: Sequence[str], min_gain: float = 0.005) -> dict[str, object]:
    """Return keep/rollback. A good image score is NOT proof of Mia's identity."""
    if not 0 < min_gain < 1:
        raise FitEvidenceError("Invalid minimum improvement")
    before = candidate_loss(reference, previous, required_views)
    after = candidate_loss(reference, proposed, required_views)
    if previous.source_geometry_sha256 != proposed.source_geometry_sha256:
        raise FitEvidenceError("Candidate was not derived from the same donor")
    unique_change = previous.geometry_sha256 != proposed.geometry_sha256
    new_images = all(previous.render_sha256[v] != proposed.render_sha256[v] for v in required_views)
    improved = unique_change and new_images and after <= before - min_gain
    return {"decision": "keep" if improved else "rollback", "before_loss": before, "after_loss": after,
            "improvement": before - after, "geometry_changed": unique_change,
            "all_views_changed": new_images, "identity_approved": False,
            "reason": "measured_gain" if improved else "no_verifiable_measured_gain"}
