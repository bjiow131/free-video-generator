import os

import pytest

from core.compositor.concatenator import VideoConcatenator


def test_anchor_ffmpeg_failure_cleans_temp_files(monkeypatch, tmp_path):
    clip = tmp_path / "anchor.mp4"
    clip.write_bytes(b"clip")
    output = tmp_path / "result.mp4"

    class Result:
        stderr = b"ffmpeg failed"

    def fail(*args, **kwargs):
        raise RuntimeError("ffmpeg unavailable")

    monkeypatch.setattr("subprocess.run", fail)

    with pytest.raises(RuntimeError, match="ffmpeg unavailable"):
        VideoConcatenator.composite_anchor_video(
            str(clip), str(tmp_path / "audio.mp3"), None,
            str(output), 5.0,
        )

    assert not (tmp_path / "_anchor_concat.txt").exists()
    assert not (tmp_path / "result_looped.mp4").exists()
