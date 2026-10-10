from __future__ import annotations

from copy import deepcopy

import pytest

from local_agent.dialogue_cues import DialogueCueError, validate_dialogue_cue


def sample_cue():
    return {
        "speaker_id": "char.mia.master",
        "line_id": "S01E01_L001",
        "text": "  Смотри, улитка!  ",
        "timing_status": "estimated_until_voiceover",
        "events": [
            {"frame": 18, "mouth_state": "open"},
            {"frame": 22, "mouth_state": "closed"},
            {"frame": 26, "mouth_state": "open"},
        ],
    }


def test_validates_and_normalizes_estimated_cue():
    result = validate_dialogue_cue(sample_cue(), frame_start=1, frame_end=240)
    assert result["text"] == "Смотри, улитка!"
    assert result["timing_status"] == "estimated_until_voiceover"
    assert result["events"][1] == {"frame": 22, "mouth_state": "closed"}


@pytest.mark.parametrize(
    "mutator",
    [
        lambda cue: cue.update(speaker_id="../outside"),
        lambda cue: cue.update(line_id=""),
        lambda cue: cue.update(text=" "),
        lambda cue: cue.update(timing_status="exact_lip_sync"),
        lambda cue: cue.update(timing_status=[]),
        lambda cue: cue.update(extra_field="run this"),
        lambda cue: cue.update(events=[]),
        lambda cue: cue.update(events=[{"frame": True, "mouth_state": "open"}]),
        lambda cue: cue.update(events=[{"frame": 0, "mouth_state": "open"}]),
        lambda cue: cue.update(events=[{"frame": 18, "mouth_state": []}]),
        lambda cue: cue.update(events=[
            {"frame": 18, "mouth_state": "open"},
            {"frame": 18, "mouth_state": "closed"},
        ]),
        lambda cue: cue.update(events=[
            {"frame": 18, "mouth_state": "open"},
            {"frame": 22, "mouth_state": "open"},
        ]),
        lambda cue: cue.update(events=[{"frame": 18, "mouth_state": "closed", "code": "x"}]),
    ],
)
def test_rejects_invalid_or_unsafe_cues(mutator):
    cue = deepcopy(sample_cue())
    mutator(cue)
    with pytest.raises(DialogueCueError):
        validate_dialogue_cue(cue, frame_start=1, frame_end=240)


def test_rejects_invalid_shot_frame_range():
    with pytest.raises(DialogueCueError, match="frame_end"):
        validate_dialogue_cue(sample_cue(), frame_start=100, frame_end=99)


def test_rejects_event_after_shot_end():
    cue = sample_cue()
    cue["events"][-1]["frame"] = 241
    with pytest.raises(DialogueCueError, match="outside the shot range"):
        validate_dialogue_cue(cue, frame_start=1, frame_end=240)


def test_does_not_mutate_input():
    cue = sample_cue()
    original = deepcopy(cue)
    validate_dialogue_cue(cue, frame_start=1, frame_end=240)
    assert cue == original
