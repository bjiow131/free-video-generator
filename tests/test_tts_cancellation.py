import asyncio

import pytest

from core.audio.tts import EdgeTTSEngine


def test_edge_tts_cancellation_removes_temp_file(monkeypatch, tmp_path):
    class Communicate:
        def __init__(self, *args, **kwargs):
            pass
        def stream(self):
            async def gen():
                await asyncio.sleep(0)
                raise asyncio.CancelledError
                yield
            return gen()

    monkeypatch.setattr("core.audio.tts.edge_tts.Communicate", Communicate)
    output = tmp_path / "out.mp3"
    tmp = tmp_path / "out.mp3.tmp"
    tmp.write_bytes(b"partial")

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await EdgeTTSEngine().generate("text", str(output))

    asyncio.run(scenario())
    assert not tmp.exists()
    assert not output.exists()
