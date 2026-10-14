"""Reusable reference-to-model fitting core, independent of any one character.

The first implementation handles calibrated multi-view landmarks and bounded
Blender controls. Image masks can be supplied as contour samples; depth is
explicitly underconstrained when a single view is provided.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Callable, Mapping, Sequence

SCHEMA_VERSION = 1
_HASH = re.compile(r"^[0-9a-f]{64}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,99}$")


class ReferenceToModelError(ValueError):
    pass


@dataclass(frozen=True)
class Observation:
    name: str
    object_name: str
    vertex_index: int
    xy: tuple[float, float]
    confidence: float
    visible: bool


@dataclass(frozen=True)
class ViewSpec:
    name: str
    camera: str
    observations: tuple[Observation, ...]
    contour: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Control:
    name: str
    kind: str
    object_name: str
    property_name: str
    component: int | None
    initial: float
    lower: float
    upper: float
    regularization: float


@dataclass(frozen=True)
class ReferenceSpec:
    reference_sha256: str
    views: tuple[ViewSpec, ...]
    controls: tuple[Control, ...]
    character_name: str


def _number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def _safe_name(x: object) -> bool:
    return isinstance(x, str) and bool(_NAME.fullmatch(x))


def parse_spec(data: object, expected_sha256: str | None = None) -> ReferenceSpec:
    """Validate a generic, hash-pinned reference-fit specification."""
    if not isinstance(data, Mapping) or data.get("schema_version") != SCHEMA_VERSION:
        raise ReferenceToModelError("schema_version_must_be_1")
    if data.get("coordinate_convention") != "camera_frame_bottom_left_normalized":
        raise ReferenceToModelError("unsupported_coordinate_convention")
    digest = data.get("reference_sha256")
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise ReferenceToModelError("reference_sha256_invalid")
    if expected_sha256 is not None and digest != expected_sha256:
        raise ReferenceToModelError("reference_sha256_mismatch")
    character = data.get("character_name", "Character")
    if not _safe_name(character):
        raise ReferenceToModelError("character_name_invalid")
    raw_views = data.get("views")
    if not isinstance(raw_views, list) or not raw_views:
        raise ReferenceToModelError("at_least_one_view_required")
    views = []
    used_views = set()
    for rv in raw_views:
        if not isinstance(rv, Mapping) or not _safe_name(rv.get("name")) or not _safe_name(rv.get("camera_name")):
            raise ReferenceToModelError("view_name_or_camera_invalid")
        if rv["name"] in used_views:
            raise ReferenceToModelError("duplicate_view_name")
        used_views.add(rv["name"])
        obs, used = [], set()
        raw_obs = rv.get("landmarks", [])
        if not isinstance(raw_obs, list):
            raise ReferenceToModelError("landmarks_must_be_list")
        for lm in raw_obs:
            if not isinstance(lm, Mapping) or not _safe_name(lm.get("name")) or not _safe_name(lm.get("object_name")):
                raise ReferenceToModelError("landmark_address_invalid")
            if lm["name"] in used:
                raise ReferenceToModelError("duplicate_landmark")
            idx, xy = lm.get("vertex_index"), lm.get("target")
            conf, visible = lm.get("confidence", 1), lm.get("visible", True)
            if isinstance(idx, bool) or not isinstance(idx, int) or idx < 0:
                raise ReferenceToModelError("vertex_index_invalid")
            if not isinstance(xy, list) or len(xy) != 2 or not all(_number(v) and 0 <= v <= 1 for v in xy):
                raise ReferenceToModelError("landmark_target_invalid")
            if not _number(conf) or not 0 <= conf <= 1 or not isinstance(visible, bool):
                raise ReferenceToModelError("landmark_confidence_or_visibility_invalid")
            used.add(lm["name"])
            obs.append(Observation(lm["name"], lm["object_name"], idx,
                                   (float(xy[0]), float(xy[1])), float(conf), visible))
        contour = rv.get("silhouette", [])
        if not isinstance(contour, list) or any(not isinstance(p, list) or len(p) != 2 or
                not all(_number(v) and 0 <= v <= 1 for v in p) for p in contour):
            raise ReferenceToModelError("silhouette_must_be_normalized_xy_samples")
        if not obs and not contour:
            raise ReferenceToModelError("each_view_needs_landmarks_or_silhouette")
        views.append(ViewSpec(rv["name"], rv["camera_name"], tuple(obs), tuple((float(p[0]), float(p[1])) for p in contour)))
    raw_controls = data.get("controls", [])
    if not isinstance(raw_controls, list):
        raise ReferenceToModelError("controls_must_be_list")
    controls, names = [], set()
    allowed = {"shape_key", "object_scale", "object_location"}
    for c in raw_controls:
        if not isinstance(c, Mapping) or not all(_safe_name(c.get(k)) for k in ("name", "kind", "object_name", "property_name")):
            raise ReferenceToModelError("control_address_invalid")
        if c["name"] in names or c["kind"] not in allowed:
            raise ReferenceToModelError("control_name_duplicate_or_kind_unsupported")
        component = c.get("component")
        if c["kind"] == "object_location" and (isinstance(component, bool) or component not in (0, 1, 2)):
            raise ReferenceToModelError("location_control_requires_component_0_1_or_2")
        if c["kind"] != "object_location" and component is not None:
            raise ReferenceToModelError("component_only_supported_for_object_location")
        vals = [c.get(k) for k in ("initial", "lower", "upper")]
        reg = c.get("regularization", 0)
        if not all(_number(v) for v in vals + [reg]) or vals[1] >= vals[2] or not vals[1] <= vals[0] <= vals[2] or reg < 0:
            raise ReferenceToModelError("control_bounds_invalid")
        names.add(c["name"])
        controls.append(Control(c["name"], c["kind"], c["object_name"], c["property_name"], component,
                               *map(float, vals), float(reg)))
    return ReferenceSpec(digest, tuple(views), tuple(controls), character)


def residual_vector(spec: ReferenceSpec, projections: Mapping[tuple[str, str], Sequence[float]],
                    control_values: Mapping[str, float] | None = None,
                    contour_projections: Mapping[str, Sequence[Sequence[float]]] | None = None) -> list[float]:
    """Confidence-weighted landmark and symmetric contour residuals.

    Contours use a sampled, symmetric nearest-neighbour distance. This is a
    useful low-cost silhouette loss, though a production raster-mask metric is
    still a later upgrade and should not be mistaken for image-level identity.
    """
    out = []
    for view in spec.views:
        for lm in view.observations:
            if not lm.visible or lm.confidence == 0:
                continue
            key = (view.name, lm.name)
            if key not in projections or len(projections[key]) != 2 or not all(_number(x) for x in projections[key]):
                raise ReferenceToModelError(f"projection_missing_or_invalid:{view.name}:{lm.name}")
            weight = math.sqrt(lm.confidence / 2)
            out.extend(( (float(projections[key][0]) - lm.xy[0]) * weight,
                         (float(projections[key][1]) - lm.xy[1]) * weight ))
        if view.contour:
            predicted = (contour_projections or {}).get(view.name)
            if not predicted:
                raise ReferenceToModelError(f"contour_projection_missing:{view.name}")
            if any(len(p) != 2 or not all(_number(x) for x in p) for p in predicted):
                raise ReferenceToModelError(f"contour_projection_invalid:{view.name}")
            target = view.contour
            # Bidirectional chamfer distances prevent a sparse predicted
            # contour from matching only a small fragment of the reference.
            for source, other in ((target, predicted), (predicted, target)):
                for point in source:
                    distance = min(math.hypot(float(point[0]) - float(q[0]),
                                              float(point[1]) - float(q[1])) for q in other)
                    out.append(distance / math.sqrt(2))
    if control_values is not None:
        for control in spec.controls:
            if control.regularization:
                if control.name not in control_values or not _number(control_values[control.name]):
                    raise ReferenceToModelError(f"control_value_missing:{control.name}")
                out.append((float(control_values[control.name]) - control.initial) * control.regularization)
    return out


def optimize(initial: Sequence[float], lower: Sequence[float], upper: Sequence[float],
             residual_fn: Callable[[Sequence[float]], Sequence[float]]) -> dict:
    """Bounded robust least squares; SciPy remains an optional local dependency."""
    if not (len(initial) == len(lower) == len(upper)) or not initial:
        return {"status": "blocked", "reason": "no_controls_or_mismatched_bounds"}
    try:
        from scipy.optimize import least_squares
    except ImportError:
        return {"status": "blocked", "reason": "scipy_not_available"}
    result = least_squares(lambda x: residual_fn(x), initial, bounds=(lower, upper),
                           loss="soft_l1", f_scale=0.01, max_nfev=120)
    return {"status": "completed" if result.success else "not_converged",
            "values": [float(x) for x in result.x], "cost": float(result.cost),
            "evaluations": int(result.nfev), "message": str(result.message)[:300]}


def characterize_ambiguity(view_count: int) -> dict:
    """Report observability limits instead of implying unseen depth was solved."""
    if isinstance(view_count, bool) or not isinstance(view_count, int) or view_count < 1:
        raise ReferenceToModelError("view_count_must_be_positive_integer")
    return {"view_count": view_count,
            "depth_confidence": "underconstrained" if view_count < 2 else "multi_view_supported",
            "requires_human_review": view_count < 3}


def build_hair_curves(bpy, collection, hair_spec: Mapping[str, object]) -> list:
    """Create independent stylized strand objects from a validated curve spec.

    Each strand is a list of 3D control points in character-local coordinates.
    The output uses Blender Curve objects with bevel profiles and can be
    replaced/regenerated without altering a donor's hair mesh or rig.
    """
    strands = hair_spec.get("strands")
    material = hair_spec.get("material")
    radius = hair_spec.get("radius")
    if not isinstance(strands, list) or not strands or not _safe_name(material):
        raise ReferenceToModelError("hair_spec_requires_strands_and_safe_material_name")
    if not _number(radius) or not 0 < radius <= 0.25:
        raise ReferenceToModelError("hair_radius_out_of_bounds")
    made = []
    for index, item in enumerate(strands):
        if not isinstance(item, Mapping) or not _safe_name(item.get("name")):
            raise ReferenceToModelError("hair_strand_name_invalid")
        points = item.get("points")
        if not isinstance(points, list) or len(points) < 2 or len(points) > 128:
            raise ReferenceToModelError("hair_strand_needs_2_to_128_points")
        if any(not isinstance(p, list) or len(p) != 3 or not all(_number(v) for v in p) for p in points):
            raise ReferenceToModelError("hair_strand_points_must_be_finite_xyz")
        curve = bpy.data.curves.new(f"{item['name']}_Curve", "CURVE")
        curve.dimensions = "3D"
        curve.resolution_u = 8
        curve.bevel_depth = float(radius)
        curve.bevel_resolution = 3
        spline = curve.splines.new("BEZIER")
        spline.bezier_points.add(len(points) - 1)
        for bp, xyz in zip(spline.bezier_points, points):
            bp.co = tuple(float(v) for v in xyz)
            bp.handle_left_type = "AUTO"
            bp.handle_right_type = "AUTO"
        obj = bpy.data.objects.new(f"Hair_{index:03d}_{item['name']}", curve)
        collection.objects.link(obj)
        obj["referencefit_hair_group"] = item.get("group", "strand")
        obj["referencefit_generated"] = True
        made.append(obj)
    return made
