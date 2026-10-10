from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_agent.blender_dialogue import apply_mouth_cue


class FakeShapeKey:
    def __init__(self, name):
        self.name = name
        self.value = 0.0
        self.inserted = []

    def keyframe_insert(self, *, data_path, frame):
        self.inserted.append((data_path, frame, self.value))


def cue(events=None):
    return {
        "speaker_id": "char.mia.master",
        "line_id": "S01E01_L001",
        "text": "Смотри, улитка!",
        "timing_status": "estimated_until_voiceover",
        "events": events or [
            {"frame": 18, "mouth_state": "open"},
            {"frame": 22, "mouth_state": "closed"},
            {"frame": 26, "mouth_state": "open"},
        ],
    }


def test_applies_mouth_open_close_to_supported_shape_key():
    key = FakeShapeKey("Mouth_Open")
    obj = SimpleNamespace(name="Mia | Head", data=SimpleNamespace(
        shape_keys=SimpleNamespace(key_blocks=[key])
    ))
    result = apply_mouth_cue(
        cue(), character_objects=[obj], frame_start=1, frame_end=240
    )
    assert result["status"] == "applied"
    assert result["shape_key"] == "Mouth_Open"
    assert result["timing_status"] == "estimated_until_voiceover"
    assert key.inserted == [
        ("value", 1, 0.0),
        ("value", 18, 1.0),
        ("value", 22, 0.0),
        ("value", 26, 1.0),
    ]


def test_explicitly_reports_unsupported_rig():
    obj = SimpleNamespace(name="Mia | Head", data=SimpleNamespace(shape_keys=None))
    result = apply_mouth_cue(
        cue(), character_objects=[obj], frame_start=1, frame_end=240
    )
    assert result["status"] == "unsupported_rig_control"
    assert result["applied_events"] == 0


def test_event_at_shot_start_overrides_initial_closed_keyframe():
    key = FakeShapeKey("mouth_open")
    obj = SimpleNamespace(data=SimpleNamespace(
        shape_keys=SimpleNamespace(key_blocks=[key])
    ))
    result = apply_mouth_cue(
        cue([{"frame": 1, "mouth_state": "open"}]),
        character_objects=[obj], frame_start=1, frame_end=240
    )
    assert result["applied_events"] == 1
    assert key.inserted == [("value", 1, 1.0)]


def test_rejects_invalid_cue_before_touching_rig():
    key = FakeShapeKey("Mouth_Open")
    obj = SimpleNamespace(data=SimpleNamespace(
        shape_keys=SimpleNamespace(key_blocks=[key])
    ))
    malformed = cue([{"frame": 999, "mouth_state": "open"}])
    with pytest.raises(ValueError):
        apply_mouth_cue(
            malformed, character_objects=[obj], frame_start=1, frame_end=240
        )
    assert key.inserted == []



def test_dialogue_cues_route_only_to_the_declared_speaker():
    from local_agent.blender_dialogue import apply_dialogue_cues

    mia_key = FakeShapeKey("Mouth_Open")
    stepa_key = FakeShapeKey("Mouth_Open")
    mia = SimpleNamespace(name="Mia | Head", data=SimpleNamespace(
        shape_keys=SimpleNamespace(key_blocks=[mia_key])
    ))
    stepa = SimpleNamespace(name="Stepa | Head", data=SimpleNamespace(
        shape_keys=SimpleNamespace(key_blocks=[stepa_key])
    ))
    result = apply_dialogue_cues(
        [cue()],
        character_objects_by_speaker={
            "char.mia.master": [mia],
            "char.stepa.master": [stepa],
        },
        frame_start=1,
        frame_end=240,
    )
    assert result["status"] == "applied"
    assert result["results"][0]["object"] == "Mia | Head"
    assert mia_key.inserted
    assert stepa_key.inserted == []


def test_missing_speaker_mapping_never_falls_back_to_another_character():
    from local_agent.blender_dialogue import apply_dialogue_cues

    unrelated_key = FakeShapeKey("Mouth_Open")
    unrelated = SimpleNamespace(name="Stepa | Head", data=SimpleNamespace(
        shape_keys=SimpleNamespace(key_blocks=[unrelated_key])
    ))
    result = apply_dialogue_cues(
        [cue()],
        character_objects_by_speaker={"char.stepa.master": [unrelated]},
        frame_start=1,
        frame_end=240,
    )
    assert result["status"] == "unsupported"
    assert result["results"][0]["status"] == "speaker_asset_not_found"
    assert unrelated_key.inserted == []


def test_dialogue_cue_batch_rejects_duplicate_line_ids():
    from local_agent.blender_dialogue import apply_dialogue_cues

    key = FakeShapeKey("Mouth_Open")
    mia = SimpleNamespace(name="Mia | Head", data=SimpleNamespace(
        shape_keys=SimpleNamespace(key_blocks=[key])
    ))
    result = apply_dialogue_cues(
        [cue(), cue()],
        character_objects_by_speaker={"char.mia.master": [mia]},
        frame_start=1,
        frame_end=240,
    )
    assert result["status"] == "rejected"
    assert result["reason"] == "duplicate_line_id"



def test_malformed_later_cue_does_not_partially_animate_earlier_speaker():
    from local_agent.blender_dialogue import apply_dialogue_cues

    key = FakeShapeKey("Mouth_Open")
    mia = SimpleNamespace(name="Mia | Head", data=SimpleNamespace(
        shape_keys=SimpleNamespace(key_blocks=[key])
    ))
    malformed = cue([{"frame": 999, "mouth_state": "open"}])
    with pytest.raises(ValueError):
        apply_dialogue_cues(
            [cue(), malformed],
            character_objects_by_speaker={"char.mia.master": [mia]},
            frame_start=1,
            frame_end=240,
        )
    assert key.inserted == []


def test_character_objects_are_indexed_only_by_explicit_stable_id():
    from local_agent.blender_dialogue import index_character_objects_by_speaker

    class TaggedObject:
        def __init__(self, name, character_id, object_type="MESH"):
            self.name = name
            self.type = object_type
            self._props = {"local_agent_character_id": character_id}

        def get(self, key):
            return self._props.get(key)

    mia_head = TaggedObject("Head", "char.mia.master")
    mia_body = TaggedObject("Body", "char.mia.master")
    untagged = TaggedObject("Stepa | Head", None)
    camera = TaggedObject("Camera", "char.stepa.master", "CAMERA")

    result = index_character_objects_by_speaker([mia_head, mia_body, untagged, camera])

    assert result["status"] == "indexed"
    assert result["character_count"] == 1
    assert result["characters"]["char.mia.master"] == [mia_head, mia_body]
    assert result["indexed_object_count"] == 2
    assert result["unindexed_objects"] == ["Stepa | Head"]
    assert result["non_mesh_objects"] == ["Camera"]


def test_character_index_rejects_unsafe_custom_property_name():
    from local_agent.blender_dialogue import index_character_objects_by_speaker

    result = index_character_objects_by_speaker([], id_property="bad[property]")
    assert result["status"] == "rejected"
    assert result["reason"] == "invalid_id_property"
