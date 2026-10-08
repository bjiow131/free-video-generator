import inspect

from core.pipelines.creative_video import CreativeVideoPipeline


def test_creative_media_saves_are_offloaded():
    source = inspect.getsource(CreativeVideoPipeline)
    assert "await asyncio.to_thread(img_output.save, ref_img_path)" in source
    assert "await asyncio.to_thread(img_output.save, end_frame_path)" in source
    assert "await asyncio.to_thread(video_output.save, video_path)" in source
