import pytest

from local_agent.mia_reference_fit import (
    ReferenceFitError,
    normalized_residuals,
    parse_reference_map,
    quality_gate,
    rms_pixel_error,
)


def reference_map():
    return {
        "schema_version": 1,
        "coordinate_convention": "camera_frame_bottom_left_normalized",
        "reference_sha256": "a" * 64,
        "views": [
            {"name": "front", "camera_name": "Ref_Front", "landmarks": [
                {"name": "eye_l", "object_name": "Head", "vertex_index": 3, "target": [0.4, 0.6], "confidence": 1.0},
                {"name": "ear_hidden", "object_name": "Head", "vertex_index": 4, "target": [0.2, 0.5], "visible": False},
            ]},
            {"name": "side", "camera_name": "Ref_Side", "landmarks": [
                {"name": "nose", "object_name": "Head", "vertex_index": 5, "target": [0.6, 0.55], "confidence": 0.25},
            ]},
        ],
        "parameters": [{"name": "head_width", "object_name": "Head", "key_name": "HeadWidth", "initial": 0.0, "lower": -0.2, "upper": 0.2, "regularization": 0.1}],
    }


def test_map_requires_approved_hash_and_multiple_fixed_views():
    parsed = parse_reference_map(reference_map(), expected_sha256="a" * 64)
    assert [view.name for view in parsed.views] == ["front", "side"]
    with pytest.raises(ReferenceFitError, match="does_not_match"):
        parse_reference_map(reference_map(), expected_sha256="b" * 64)


def test_unknown_or_out_of_frame_measurements_are_rejected():
    data = reference_map()
    data["views"][0]["landmarks"][0]["target"] = [1.2, 0.6]
    with pytest.raises(ReferenceFitError, match="normalized_camera_frame"):
        parse_reference_map(data)


def test_projection_residuals_skip_occluded_points_and_weight_confidence():
    parsed = parse_reference_map(reference_map())
    residuals = normalized_residuals(parsed, {
        ("front", "eye_l"): [0.5, 0.6],
        ("side", "nose"): [0.8, 0.55],
    })
    assert len(residuals) == 4
    assert residuals[0] == pytest.approx(0.1 / 2**0.5)
    assert residuals[2] == pytest.approx(0.2 / 4)
    assert rms_pixel_error(residuals, 1000, 1000) > 0


def test_quality_gate_rejects_improvement_paid_for_by_one_worse_view():
    result = quality_gate(10, 8, {"front": 8, "side": 2}, {"front": 5, "side": 3})
    assert result["status"] == "reject"
    assert "side" in result["regressed_views"]


def test_quality_gate_accepts_measurable_all_view_gain():
    result = quality_gate(10, 8, {"front": 8, "side": 2}, {"front": 7, "side": 1.9})
    assert result["status"] == "accept"
    assert result["relative_gain"] == pytest.approx(0.2)
