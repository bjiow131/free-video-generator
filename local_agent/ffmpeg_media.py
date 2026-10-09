"""FFmpeg/ffprobe media adapter for local video projects.

No shell is used. Stream-copy concatenation is intentionally strict: clips with
incompatible stream layouts are rejected rather than silently transcoded.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class MediaError(RuntimeError):
    """Actionable media validation or FFmpeg execution failure."""


class FFmpegMediaTools:
    def __init__(
        self,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        *,
        timeout: float = 120.0,
        max_probe_bytes: int = 4_000_000,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.timeout = timeout
        self.max_probe_bytes = max_probe_bytes

    def _run(self, args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                args, shell=False, check=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=self.timeout if timeout is None else timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise MediaError(f"Command timed out after {exc.timeout} seconds: {Path(args[0]).name}") from exc
        except OSError as exc:
            raise MediaError(f"Could not start {Path(args[0]).name}; verify FFmpeg is installed and on PATH") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout or "no diagnostic output").strip()
            raise MediaError(f"{Path(args[0]).name} failed (exit {result.returncode}): {detail[-1800:]}")
        return result

    def _probe(self, path: str | os.PathLike[str]) -> dict[str, Any]:
        file_path = Path(path)
        if not file_path.is_file() or file_path.stat().st_size == 0:
            raise MediaError(f"Media file is missing or empty: {file_path.name}")
        result = self._run([
            self.ffprobe, "-v", "error", "-show_entries",
            "format=duration,format_name:stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,sample_rate,channels",
            "-of", "json", str(file_path),
        ])
        if len(result.stdout.encode("utf-8", errors="replace")) > self.max_probe_bytes:
            raise MediaError("ffprobe response exceeded the configured size limit")
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise MediaError("ffprobe returned malformed JSON") from exc
        if not isinstance(data, dict) or not isinstance(data.get("streams"), list):
            raise MediaError("ffprobe response has no valid stream metadata")
        return data

    def validate_video(self, path: str, expected_duration: int) -> None:
        if expected_duration < 1:
            raise ValueError("expected_duration must be positive")
        data = self._probe(path)
        videos = [s for s in data["streams"] if isinstance(s, dict) and s.get("codec_type") == "video"]
        if not videos:
            raise MediaError("File contains no video stream")
        duration = (data.get("format") or {}).get("duration")
        try:
            seconds = float(duration)
        except (TypeError, ValueError) as exc:
            raise MediaError("Video duration is missing or invalid") from exc
        if not 0.05 <= seconds <= 24 * 60 * 60:
            raise MediaError(f"Video duration is unreasonable: {seconds}")
        # Generators can differ slightly from the requested duration.
        if abs(seconds - expected_duration) > max(3.0, expected_duration * 0.6):
            raise MediaError(f"Video duration {seconds:.2f}s is inconsistent with requested {expected_duration}s")
        video = videos[0]
        if not isinstance(video.get("width"), int) or not isinstance(video.get("height"), int):
            raise MediaError("Video dimensions are missing")
        if video["width"] < 2 or video["height"] < 2:
            raise MediaError("Video dimensions are invalid")

    def validate_image(self, path: str) -> None:
        data = self._probe(path)
        if not any(isinstance(s, dict) and s.get("codec_type") == "video" for s in data["streams"]):
            raise MediaError("Reference image is not a readable image/video stream")

    def extract_last_frame(self, video_path: str, output_path: str) -> str:
        self._probe(video_path)
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._run([
            self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-sseof", "-1", "-i", str(video_path), "-map", "0:v:0",
            "-frames:v", "1", "-f", "image2", str(target),
        ])
        if not target.is_file() or target.stat().st_size == 0:
            raise MediaError("FFmpeg did not produce the final-frame image")
        self.validate_image(str(target))
        return str(target)

    @staticmethod
    def _stream_signature(data: dict[str, Any]) -> tuple[Any, ...]:
        streams = data["streams"]
        videos = [s for s in streams if s.get("codec_type") == "video"]
        audios = [s for s in streams if s.get("codec_type") == "audio"]
        if len(videos) != 1 or len(audios) > 1:
            raise MediaError("Stream-copy concat requires exactly one video stream and at most one audio stream per clip")
        def fields(stream: dict[str, Any], keys: tuple[str, ...]) -> tuple[Any, ...]:
            return tuple(stream.get(k) for k in keys)
        video_sig = fields(videos[0], ("codec_name", "width", "height", "avg_frame_rate", "r_frame_rate"))
        audio_sig = fields(audios[0], ("codec_name", "sample_rate", "channels")) if audios else None
        return video_sig, audio_sig

    def concatenate(self, video_paths: list[str], output_path: str) -> str:
        if not video_paths:
            raise MediaError("No clips were provided for assembly")
        signatures = []
        for path in video_paths:
            data = self._probe(path)
            signatures.append(self._stream_signature(data))
        if any(signature != signatures[0] for signature in signatures[1:]):
            raise MediaError("Clips have incompatible codecs, dimensions, frame rates, or audio streams; stream-copy concat refused")
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Keep list file beside target so paths with spaces and non-ASCII characters
        # are handled consistently by FFmpeg on Windows.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", suffix=".ffconcat",
            prefix="concat_", dir=target.parent, delete=False,
        ) as listing:
            list_path = Path(listing.name)
            for path in video_paths:
                absolute = str(Path(path).resolve()).replace("\\", "/")
                escaped = absolute.replace("'", "'\\''")
                listing.write(f"file '{escaped}'\n")
        try:
            self._run([
                self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(list_path),
                "-c", "copy", str(target),
            ])
        finally:
            try:
                list_path.unlink(missing_ok=True)
            except OSError:
                pass
        if not target.is_file() or target.stat().st_size == 0:
            raise MediaError("FFmpeg did not produce the assembled video")
        return str(target)
