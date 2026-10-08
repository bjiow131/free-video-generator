import inspect

from core.pipelines.manuscript_video import ManuscriptVideoPipeline


def test_manuscript_video_save_is_offloaded():
    source = inspect.getsource(ManuscriptVideoPipeline)
    assert "await asyncio.to_thread(video_output.save, video_path)" in source
