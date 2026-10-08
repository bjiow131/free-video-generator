from models.task import SubtitleStyle


def test_transparent_subtitle_background_remains_tuple():
    style = SubtitleStyle(bg_color="transparent")
    assert style.bg_color == (0, 0, 0, 0)
