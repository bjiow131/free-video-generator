import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from local_agent.ffmpeg_media import FFmpegMediaTools, MediaError


def probe_result(*, video=True, audio=False, duration="5.0", width=720, height=1280):
    streams = []
    if video:
        streams.append({
            "codec_type": "video", "codec_name": "h264", "width": width,
            "height": height, "avg_frame_rate": "25/1", "r_frame_rate": "25/1",
        })
    if audio:
        streams.append({
            "codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2,
        })
    return {"format": {"duration": duration, "format_name": "mov,mp4"}, "streams": streams}


def completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=["fake"], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.mark.parametrize("timeout", [0, -1, True, "2"])
def test_constructor_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="timeout must be a positive number"):
        FFmpegMediaTools(timeout=timeout)


@pytest.mark.parametrize("max_probe_bytes", [0, -1, True, 1.5, "100"])
def test_constructor_rejects_invalid_probe_size_limit(max_probe_bytes):
    with pytest.raises(ValueError, match="max_probe_bytes must be a positive integer"):
        FFmpegMediaTools(max_probe_bytes=max_probe_bytes)


@pytest.mark.parametrize("expected_duration", [0, -1, True, 5.0, "5"])
def test_validate_video_rejects_invalid_expected_duration(tmp_path, expected_duration):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x")
    with pytest.raises(ValueError, match="expected_duration must be a positive integer"):
        FFmpegMediaTools().validate_video(str(path), expected_duration)


def test_probe_uses_argument_list_and_shell_false(tmp_path, monkeypatch):
    path = tmp_path / "видео файл.mp4"
    path.write_bytes(b"x")
    run = Mock(return_value=completed(json.dumps(probe_result())))
    monkeypatch.setattr("local_agent.ffmpeg_media.subprocess.run", run)
    media = FFmpegMediaTools()
    media.validate_video(str(path), 5)
    args, kwargs = run.call_args
    assert str(path) in args[0]
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 120.0


def test_missing_and_empty_media_rejected(tmp_path):
    media = FFmpegMediaTools()
    with pytest.raises(MediaError, match="missing or empty"):
        media.validate_video(str(tmp_path / "missing.mp4"), 5)
    empty = tmp_path / "empty.mp4"
    empty.touch()
    with pytest.raises(MediaError, match="missing or empty"):
        media.validate_video(str(empty), 5)


def test_video_without_video_stream_rejected(tmp_path, monkeypatch):
    path = tmp_path / "audio.mp4"
    path.write_bytes(b"x")
    monkeypatch.setattr(
        "local_agent.ffmpeg_media.subprocess.run",
        Mock(return_value=completed(json.dumps(probe_result(video=False, audio=True)))),
    )
    with pytest.raises(MediaError, match="no video stream"):
        FFmpegMediaTools().validate_video(str(path), 5)


@pytest.mark.parametrize("duration", ["1.0", "3.7", "6.3", "10.0"])
def test_materially_short_or_long_video_duration_rejected(tmp_path, monkeypatch, duration):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video")
    monkeypatch.setattr(
        "local_agent.ffmpeg_media.subprocess.run",
        Mock(return_value=completed(json.dumps(probe_result(duration=duration)))),
    )

    with pytest.raises(MediaError, match="inconsistent with requested"):
        FFmpegMediaTools().validate_video(str(path), 5)


def test_small_video_duration_difference_is_accepted(tmp_path, monkeypatch):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video")
    monkeypatch.setattr(
        "local_agent.ffmpeg_media.subprocess.run",
        Mock(return_value=completed(json.dumps(probe_result(duration="5.8")))),
    )

    FFmpegMediaTools().validate_video(str(path), 5)


def test_invalid_duration_rejected(tmp_path, monkeypatch):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x")
    monkeypatch.setattr(
        "local_agent.ffmpeg_media.subprocess.run",
        Mock(return_value=completed(json.dumps(probe_result(duration="999")))),
    )
    with pytest.raises(MediaError, match="inconsistent"):
        FFmpegMediaTools().validate_video(str(path), 5)


def test_timeout_and_missing_executable_are_actionable(monkeypatch):
    monkeypatch.setattr(
        "local_agent.ffmpeg_media.subprocess.run",
        Mock(side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=2)),
    )
    with pytest.raises(MediaError, match="timed out"):
        FFmpegMediaTools(timeout=2)._run(["ffprobe", "x"])
    monkeypatch.setattr(
        "local_agent.ffmpeg_media.subprocess.run",
        Mock(side_effect=FileNotFoundError()),
    )
    with pytest.raises(MediaError, match="installed"):
        FFmpegMediaTools()._run(["ffprobe", "x"])


def test_extract_frame_uses_safe_args_and_unicode_paths(tmp_path, monkeypatch):
    source = tmp_path / "вход.mp4"
    source.write_bytes(b"x")
    target = tmp_path / "выход кадр.png"
    calls = []
    def fake_run(args, **kwargs):
        calls.append(args)
        if args[0] == "ffprobe":
            if str(source) in args:
                return completed(json.dumps(probe_result()))
            target.write_bytes(b"png")
            return completed(json.dumps({"streams": [{"codec_type": "video"}]}))
        target.write_bytes(b"png")
        return completed()
    monkeypatch.setattr("local_agent.ffmpeg_media.subprocess.run", fake_run)
    result = FFmpegMediaTools().extract_last_frame(str(source), str(target))
    assert result == str(target)
    ffmpeg_args = next(args for args in calls if args[0] == "ffmpeg")
    assert str(source) in ffmpeg_args and str(target) in ffmpeg_args
    assert "-frames:v" in ffmpeg_args
    assert ffmpeg_args[ffmpeg_args.index("-vf") + 1] == "reverse"


@pytest.mark.parametrize("streams", [[None], ["not-a-stream"], [1]])
def test_concat_rejects_malformed_probe_stream_entries(tmp_path, monkeypatch, streams):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    responses = [
        probe_result(),
        {"format": {"duration": "5.0"}, "streams": streams},
    ]

    def fake_run(args, **kwargs):
        if args[0] == "ffprobe":
            return completed(json.dumps(responses.pop(0)))
        raise AssertionError("FFmpeg must not run for malformed stream metadata")

    monkeypatch.setattr("local_agent.ffmpeg_media.subprocess.run", fake_run)
    with pytest.raises(MediaError, match="malformed stream metadata"):
        FFmpegMediaTools().concatenate([str(first), str(second)], str(tmp_path / "out.mp4"))


def test_concat_rejects_incompatible_clips_before_encoding(tmp_path, monkeypatch):
    paths = []
    for name in ("a.mp4", "b.mp4"):
        path = tmp_path / name
        path.write_bytes(b"x")
        paths.append(path)
    responses = [probe_result(width=720), probe_result(width=1080)]
    def fake_run(args, **kwargs):
        if args[0] == "ffprobe":
            return completed(json.dumps(responses.pop(0)))
        raise AssertionError("ffmpeg must not run for incompatible clips")
    monkeypatch.setattr("local_agent.ffmpeg_media.subprocess.run", fake_run)
    with pytest.raises(MediaError, match="incompatible"):
        FFmpegMediaTools().concatenate([str(p) for p in paths], str(tmp_path / "final.mp4"))


def test_concat_preserves_order_and_cleans_list_file(tmp_path, monkeypatch):
    paths = []
    for name in ("первый клип.mp4", "second.mp4"):
        path = tmp_path / name
        path.write_bytes(b"x")
        paths.append(path)
    calls = []
    def fake_run(args, **kwargs):
        calls.append(args)
        if args[0] == "ffprobe":
            return completed(json.dumps(probe_result()))
        Path(args[-1]).write_bytes(b"final")
        return completed()
    monkeypatch.setattr("local_agent.ffmpeg_media.subprocess.run", fake_run)
    output = tmp_path / "итог.mp4"
    result = FFmpegMediaTools().concatenate([str(p) for p in paths], str(output))
    assert result == str(output)
    args = next(args for args in calls if args[0] == "ffmpeg")
    assert args[args.index("-c") + 1] == "copy"
    listing = Path(args[args.index("-i") + 1])
    assert not listing.exists()
    assert output.read_bytes() == b"final"



def test_concat_refuses_to_overwrite_input_clip(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    with pytest.raises(MediaError, match="must not overwrite"):
        FFmpegMediaTools().concatenate([str(source)], str(source))


def test_frame_extraction_refuses_to_overwrite_source(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    with pytest.raises(MediaError, match="must not overwrite"):
        FFmpegMediaTools().extract_last_frame(str(source), str(source))
