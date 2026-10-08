import json

import pytest

from core.pipelines.simple_video import SimpleVideoPipeline


def test_save_task_removes_partial_file_on_write_failure(monkeypatch, tmp_path):
    pipeline = object.__new__(SimpleVideoPipeline)
    pipeline.working_dir = str(tmp_path)

    real_dump = json.dump
    def fail_dump(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(json, "dump", fail_dump)

    with pytest.raises(OSError, match="disk full"):
        pipeline._save_task("video-123")

    assert not (tmp_path / "task.json.tmp").exists()


def test_simple_pipeline_saves_video_off_async_loop():
    import inspect
    source = inspect.getsource(SimpleVideoPipeline)
    assert "await asyncio.to_thread(video_output.save, video_path)" in source
