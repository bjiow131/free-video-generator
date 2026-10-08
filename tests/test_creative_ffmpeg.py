import asyncio

import pytest

from core.pipelines import creative_video


def test_ffmpeg_process_is_killed_when_cancelled(monkeypatch):
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

    monkeypatch.setattr(creative_video.asyncio, "create_subprocess_exec", create)

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await creative_video._run_ffmpeg_async(["ffmpeg", "-version"])

    asyncio.run(scenario())
    assert proc.killed is True
