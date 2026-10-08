import pytest

from core.compositor.concatenator import VideoConcatenator


def test_anchor_concat_escapes_apostrophe_and_backslash(monkeypatch, tmp_path):
    clip = tmp_path / "clip's.mp4"
    clip.write_bytes(b"clip")
    output = tmp_path / "out.mp4"

    def fail(*args, **kwargs):
        concat_file = tmp_path / "_anchor_concat.txt"
        content = concat_file.read_text(encoding="utf-8")
        assert "clip'\\\\''s.mp4" in content
        raise RuntimeError("stop")

    monkeypatch.setattr("subprocess.run", fail)

    with pytest.raises(RuntimeError, match="stop"):
        VideoConcatenator.composite_anchor_video(
            str(clip), str(tmp_path / "audio.mp3"), None,
            str(output), 5.0,
        )
