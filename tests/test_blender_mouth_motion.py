from local_agent.blender_mouth_motion import _blender_script


def test_blender_adapter_maps_each_speaker_to_a_matching_mouth_control():
    script = _blender_script()
    assert "mouth_shape_key_not_found" in script
    assert "mouth_control_missing_or_ambiguous_for_speaker" in script
    assert "assignment[speaker]" in script
    assert "Original" not in script  # runtime note is returned by the Python adapter, not executed in Blender


def test_blender_adapter_refuses_existing_shape_key_animation():
    script = _blender_script()
    assert "shape_key_animation_already_exists" in script
    assert 'point.interpolation="CONSTANT"' in script
    assert 'bpy.ops.wm.save_as_mainfile(filepath=cfg["output"])' in script



def test_speech_animation_requires_a_fresh_face_rig_preflight():
    from inspect import getsource
    from local_agent.blender_mouth_motion import apply_mouth_motion

    source = getsource(apply_mouth_motion)
    assert "check_face_rig(" in source
    assert 'report_name="face_rig_preflight_for_mouth_motion.json"' in source
    assert "facial_rig_preflight_not_ready" in source
    assert "no_supported_mouth_open_shape_key" in source


def test_face_rig_preflight_uses_supported_mouth_open_names():
    script = _blender_script()
    assert "mouth_shape_key_not_found" in script
    assert "mouth_open" in script
