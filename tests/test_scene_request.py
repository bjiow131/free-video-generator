from __future__ import annotations

import pytest

from local_agent.scene_request import SceneRequestError, parse_scene_request


def test_parses_russian_counts_colors_and_vertical_aspect():
    plan = parse_scene_request("Три красных куба и синяя сфера, вертикально 9:16")
    assert len(plan["objects"]) == 4
    assert [item["primitive"] for item in plan["objects"]] == [
        "cube", "cube", "cube", "uv_sphere"
    ]
    assert all(item["color_name"] == "red" for item in plan["objects"][:3])
    assert plan["objects"][3]["color_name"] == "blue"
    assert plan["aspect_ratio"] == "9:16"
    assert plan["resolution"] == [720, 1280]


def test_parses_russian_word_count_and_square_layout():
    plan = parse_scene_request("Создай пять зелёных сфер, квадрат")
    assert len(plan["objects"]) == 5
    assert all(item["primitive"] == "uv_sphere" for item in plan["objects"])
    assert all(item["color_name"] == "green" for item in plan["objects"])
    assert plan["aspect_ratio"] == "1:1"


def test_parses_numeric_count_without_treating_aspect_ratio_as_object_count():
    plan = parse_scene_request("Сделай вертикальную сцену 9:16 с одним жёлтым кубом")
    assert len(plan["objects"]) == 1
    assert plan["objects"][0]["primitive"] == "cube"
    assert plan["aspect_ratio"] == "9:16"


@pytest.mark.parametrize("prompt", ["", "   ", "создай красивый пейзаж", "x" * 1201])
def test_rejects_empty_unsupported_or_oversized_prompt(prompt: str):
    with pytest.raises(SceneRequestError):
        parse_scene_request(prompt)


def test_rejects_excessive_object_count():
    with pytest.raises(SceneRequestError, match="limited to"):
        parse_scene_request("Создай 41 куб")


def test_scale_number_is_not_mistaken_for_object_count():
    plan = parse_scene_request("Куб размером 2 и сфера")
    assert len(plan["objects"]) == 2
    assert all(item["scale"] == 2.0 for item in plan["objects"])
