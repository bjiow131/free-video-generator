import pytest
from local_agent.multiscene_timeline import Segment, compile_timeline


def test_contiguous_frames_and_positions():
    result = compile_timeline([
        Segment("intro", 2, camera_dx=0.5),
        Segment("move", 2, object_dx=1.5),
        Segment("outro", 2, camera_dx=0.3, object_dx=1),
    ])
    assert [(x.start_frame, x.end_frame) for x in result] == [
        (1, 24), (25, 48), (49, 72)
    ]
    assert [(x.camera_x, x.object_x) for x in result] == [
        (0.5, 0), (0.5, 1.5), (0.8, 2.5)
    ]


@pytest.mark.parametrize("segments", [
    [], [Segment("", 1)], [Segment("x", 0)],
    [Segment("x", float("nan"))], [Segment("x", float("inf"))],
    [Segment("x", 0.001)], [Segment("x", 1, camera_dx=float("inf"))],
])
def test_invalid_segments(segments):
    with pytest.raises((ValueError, TypeError)):
        compile_timeline(segments)


def test_limit_and_fps_validation():
    with pytest.raises(ValueError):
        compile_timeline([Segment("x", 2)], max_frames=10)
    with pytest.raises(ValueError):
        compile_timeline([Segment("x", 2)], fps=0)
