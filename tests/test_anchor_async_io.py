import inspect

from core.pipelines.anchor_video import AnchorPipeline


def test_anchor_media_saves_are_offloaded():
    source = inspect.getsource(AnchorPipeline)
    assert "await asyncio.to_thread(img_output.save, output_path)" in source
    assert "await asyncio.to_thread(video_output.save, clip_path)" in source
