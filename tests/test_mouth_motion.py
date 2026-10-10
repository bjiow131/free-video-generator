from local_agent.mouth_motion import compile_mouth_motion


def test_dialogue_creates_coarse_open_close_cues_without_audio():
    scenes = [{
        "scene_id": "scene_001",
        "dialogue": [{"speaker": "Mia", "text": "Look at the snail!"}],
    }]
    timeline = {
        "fps": 24,
        "clips": [{"scene_id": "scene_001", "start_frame": 1, "end_frame": 240}],
    }
    result = compile_mouth_motion(scenes, timeline)
    assert result["audio_required"] is False
    assert result["phoneme_alignment"] is False
    assert result["readiness"] == "planning_only"
    assert result["cue_count"] > 1
    assert {cue["mouth"] for cue in result["cues"]} == {"open", "closed"}
    assert all(cue["requires"] == "character_mouth_rig" for cue in result["cues"])


def test_no_dialogue_produces_no_mouth_motion():
    result = compile_mouth_motion(
        [{"scene_id": "scene_001", "dialogue": []}],
        {"fps": 24, "clips": [{"scene_id": "scene_001", "start_frame": 1, "end_frame": 120}]},
    )
    assert result["cues"] == []
    assert result["cue_count"] == 0


def test_dialogue_without_timeline_clip_is_reported_not_guessed():
    result = compile_mouth_motion(
        [{"scene_id": "scene_002", "dialogue": [{"speaker": "Mia", "text": "Hello"}]}],
        {"fps": 24, "clips": []},
    )
    assert result["cues"] == []
    assert result["warnings"][0]["scene_id"] == "scene_002"


def test_multiple_speakers_are_preserved_in_cues():
    result = compile_mouth_motion(
        [{"scene_id": "scene_001", "dialogue": [
            {"speaker": "Mia", "text": "Hello there!"},
            {"speaker": "Friend", "text": "Hi, Mia!"},
        ]}],
        {"fps": 24, "clips": [{"scene_id": "scene_001", "start_frame": 101, "end_frame": 340}]},
    )
    assert {cue["speaker"] for cue in result["cues"]} == {"Mia", "Friend"}
    assert min(cue["frame_start"] for cue in result["cues"]) >= 101
    assert max(cue["frame_end"] for cue in result["cues"]) <= 340
