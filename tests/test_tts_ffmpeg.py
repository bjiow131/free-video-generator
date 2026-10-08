import asyncio

import pytest

from core.audio.tts import SilentTTSEngine


def test_silent_tts_kills_ffmpeg_on_cancellation(monkeypatch, tmp_path):
    class Proc:
        returncode = None
        killed = False
        def kill(self):
            self.killed = True
            self.returncode = -9
        async def communicate(self):
            raise asyncio.CancelledError
        async def wait(self):
            return self.returncode

    proc = Proc()

    async def create(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await SilentTTSEngine().generate("text", str(tmp_path / "out.mp3"))

    asyncio.run(scenario())
    assert proc.killed is True


def test_silent_tts_removes_partial_output_on_ffmpeg_failure(monkeypatch, tmp_path):
    class Proc:
        returncode = 1
        async def communicate(self):
            return b"", b"ffmpeg failed"
    async def create(*args, **kwargs):
        (tmp_path / "out.mp3").write_bytes(b"partial")
        return Proc()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)

    with pytest.raises(RuntimeError, match="ffmpeg silent generation failed"):
        asyncio.run(SilentTTSEngine().generate("text", str(tmp_path / "out.mp3")))
    assert not (tmp_path / "out.mp3").exists()
