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
