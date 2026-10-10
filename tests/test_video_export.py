from pathlib import Path
import pytest
from local_agent.video_export import PRESETS, VideoExportError, _SCRIPT, export_animation_to_mp4

def test_platform_presets():
    assert PRESETS["TikTok"]["resolution"] == [1080, 1920]
    assert PRESETS["YouTube"]["resolution"] == [1920, 1080]
    assert PRESETS["YouTube Shorts"]["aspect_ratio"] == "9:16"
    assert PRESETS["Instagram Reels"]["fps"] == 30

def test_export_validates_project_preset_and_extension(tmp_path: Path):
    with pytest.raises(VideoExportError):
        export_animation_to_mp4(tmp_path/"missing.blend", tmp_path/"out.mp4", "TikTok", tmp_path/"blender.exe")
    blend=tmp_path/"scene.blend"; blender=tmp_path/"blender.exe"
    blend.write_bytes(b"test"); blender.write_bytes(b"test")
    with pytest.raises(VideoExportError, match="расширение"):
        export_animation_to_mp4(blend, tmp_path/"out.mov", "TikTok", blender)
    with pytest.raises(VideoExportError, match="Неизвестный"):
        export_animation_to_mp4(blend, tmp_path/"out.mp4", "Unknown", blender)

def test_generated_export_script_has_valid_python_syntax():
    compile(_SCRIPT, "blender_video_export.py", "exec")
