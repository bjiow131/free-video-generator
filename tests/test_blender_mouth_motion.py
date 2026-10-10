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
