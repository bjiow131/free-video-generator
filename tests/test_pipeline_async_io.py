import asyncio

from core.pipelines import BasePipeline


def test_generate_subtitles_uses_thread_for_ffprobe(monkeypatch, tmp_path):
    pipeline = object.__new__(BasePipeline)
    pipeline.task_manager = type("TM", (), {"task_dir": str(tmp_path)})()
    called = {"to_thread": False}

    async def fake_to_thread(fn, *args, **kwargs):
        called["to_thread"] = True
        return 1.0

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    class Style:
        style_mode = "fixed"
        style_hints = ""

    class Config:
        enabled = False
        style = Style()

    result = asyncio.run(
        pipeline.generate_subtitles_common(
            ["text"], [1.0], Config(), audio_path=""
        )
    )
    assert result[0]
    assert called["to_thread"] is True
