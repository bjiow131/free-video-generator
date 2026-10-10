from __future__ import annotations

import pytest

from local_agent.timeline import TimelineError, compile_timeline


def scenes():
    return [
        {"scene_id": "intro", "title": "Intro", "duration_seconds": 4, "transition": "crossfade"},
        {"scene_id": "middle", "title": "Middle", "duration_seconds": 6, "transition": "cut"},
        {"scene_id": "ending", "title": "Ending", "duration_seconds": 3, "transition": "cut"},
    ]


def test_builds_sequential_timeline_with_crossfade_overlap():
    timeline = compile_timeline(scenes(), fps=24)
    clips = timeline["clips"]
    assert clips[0]["start_frame"] == 1
    assert clips[0]["end_frame"] == 96
    assert clips[0]["overlap_frames"] == 12
    assert clips[1]["start_frame"] == 85
    assert clips[1]["end_frame"] == 228
    assert clips[2]["start_frame"] == 229
    assert timeline["total_frames"] == 300
    assert timeline["readiness"] == "planning_only"


def test_unknown_transition_falls_back_to_cut_with_warning():
    timeline = compile_timeline([
        {"scene_id": "one", "duration_seconds": 2, "transition": "magic_portal"},
        {"scene_id": "two", "duration_seconds": 2, "transition": "cut"},
    ])
    assert timeline["clips"][0]["transition_out"] == "cut"
    assert timeline["clips"][0]["overlap_frames"] == 0
    assert len(timeline["warnings"]) == 1


@pytest.mark.parametrize("fps", [True, 0, 121, 24.0, "24"])
def test_rejects_invalid_fps(fps):
    with pytest.raises(TimelineError):
        compile_timeline(scenes(), fps=fps)


@pytest.mark.parametrize("bad_scenes", [[], [{}], [{"duration_seconds": True}], [{"duration_seconds": 121}]])
def test_rejects_invalid_scene_timing(bad_scenes):
    with pytest.raises(TimelineError):
        compile_timeline(bad_scenes)


def test_final_scene_transition_is_reported_as_ignored():
    timeline = compile_timeline([
        {"scene_id": "one", "duration_seconds": 2, "transition": "cut"},
        {"scene_id": "two", "duration_seconds": 2, "transition": "crossfade"},
    ])
    assert timeline["clips"][-1]["transition_out"] == "cut"
    assert any("Final scene" in item["message"] for item in timeline["warnings"])
