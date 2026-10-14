from dataclasses import replace
import pytest
from local_agent.mia_fit_metrics import MeasuredView, FitCandidate, FitEvidenceError, mask_iou, view_loss, decide_improvement


def sample(mask: bytes, *, view="front", camera="locked_front", features=None):
    return MeasuredView(view, camera, 16, 16, {"silhouette": mask}, features or {"left_eye": (0.3, 0.2)})


def filled(start=0, count=24):
    return bytes(1 if start <= i < start + count else 0 for i in range(256))


def make_candidate(view, geometry, render, source="a" * 64):
    return FitCandidate(geometry, source, geometry * 64, {"front": render * 64}, {"front": view})


def test_identical_view_has_zero_loss():
    a = sample(filled())
    assert view_loss(a, a) == 0.0


def test_mask_scorer():
    assert mask_iou(filled(0, 24), filled(12, 24)) == pytest.approx(1 / 3)


def test_better_geometry_is_accepted_but_not_identity_approved():
    target = sample(filled())
    old = make_candidate(sample(filled(12)), "b", "c")
    new = make_candidate(sample(filled()), "d", "e")
    verdict = decide_improvement({"front": target}, old, new, ["front"])
    assert verdict["decision"] == "keep"
    assert verdict["identity_approved"] is False


def test_identical_images_and_geometry_are_rejected():
    target = sample(filled())
    old = make_candidate(sample(filled(12)), "b", "c")
    assert decide_improvement({"front": target}, old, old, ["front"])["decision"] == "rollback"


def test_misaligned_camera_rejected():
    with pytest.raises(FitEvidenceError, match="cameras"):
        view_loss(sample(filled()), sample(filled(), camera="different"))


def test_missing_region_cannot_count_as_perfect():
    target = sample(filled())
    empty = replace(target, regions={})
    with pytest.raises(FitEvidenceError, match="Silhouette"):
        view_loss(target, empty)


def test_two_empty_masks_no_false_perfection():
    with pytest.raises(FitEvidenceError, match="empty"):
        mask_iou(bytes(256), bytes(256))


def test_changed_geometry_but_worse_score_rolls_back():
    target = sample(filled())
    old = make_candidate(sample(filled()), "b", "c")
    new = make_candidate(sample(filled(12)), "d", "e")
    assert decide_improvement({"front": target}, old, new, ["front"])["decision"] == "rollback"


def test_incompatible_donor_is_rejected():
    target = sample(filled())
    old = make_candidate(sample(filled(12)), "b", "c")
    new = make_candidate(sample(filled()), "d", "e", source="f" * 64)
    with pytest.raises(FitEvidenceError, match="same donor"):
        decide_improvement({"front": target}, old, new, ["front"])
