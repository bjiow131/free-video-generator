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


@pytest.mark.parametrize("prompt", ["", "   ", "создай абстрактное настроение", "x" * 1201])
def test_rejects_empty_unsupported_or_oversized_prompt(prompt: str):
    with pytest.raises(SceneRequestError):
        parse_scene_request(prompt)


def test_rejects_excessive_object_count():
    with pytest.raises(SceneRequestError, match="не более"):
        parse_scene_request("Создай 41 куб")


def test_scale_number_is_not_mistaken_for_object_count():
    plan = parse_scene_request("Куб размером 2 и сфера")
    assert len(plan["objects"]) == 2
    assert all(item["scale"] == 2.0 for item in plan["objects"])


def test_composite_objects_environment_style_and_vertical_format():
    from local_agent.scene_language import parse_scene_request as compile_prompt

    plan = compile_prompt("Создай деревянный дом, две ёлки и красную машину в лесу, low poly, вертикально 9:16")
    assert [item["primitive"] for item in plan["objects"]] == ["house", "tree", "tree", "car"]
    assert plan["environment"] == "forest"
    assert plan["style"] == "low_poly"
    assert plan["aspect_ratio"] == "9:16"
    assert plan["objects"][-1]["color_name"] == "red"


def test_scene_only_prompt_gets_a_starter_composition():
    from local_agent.scene_language import parse_scene_request as compile_prompt

    forest = compile_prompt("Создай красивый лес на закате")
    assert forest["objects"][0]["primitive"] == "tree"
    assert forest["environment"] == "forest"
    assert forest["lighting"] == "sunset"


def test_animation_and_render_quality_are_encoded_as_data():
    from local_agent.scene_language import parse_scene_request as compile_prompt

    plan = compile_prompt("Сделай вращающуюся золотую ракету, анимация 4 секунды, высокое качество")
    assert plan["objects"][0]["primitive"] == "rocket"
    assert plan["objects"][0]["color_name"] == "gold"
    assert plan["animation"]["enabled"] is True
    assert plan["animation"]["kind"] == "rotate"
    assert plan["render_percentage"] == 75


def test_catalog_includes_every_supported_composite_family():
    from local_agent.scene_language import OBJECTS

    names = {name for name, _aliases in OBJECTS}
    assert {"tree", "house", "mountain", "cloud", "person", "car", "table", "chair",
            "lamp", "bench", "flower", "grass", "rock", "road", "fence", "bed",
            "book", "mug", "bottle", "smartphone", "rocket", "sun", "moon", "star"} <= names


def test_mia_scooter_snail_prompt_is_compiled_from_text_only():
    from local_agent.scene_language import parse_scene_request as compile_prompt

    plan = compile_prompt("Создай Мию на жёлтом самокате рядом с улиткой, мультяшный стиль, 9:16")
    assert [item["primitive"] for item in plan["objects"]] == ["mia", "scooter", "snail"]
    assert plan["style"] == "cartoon"
    assert plan["aspect_ratio"] == "9:16"


def test_thematic_scene_catalog_includes_additional_families():
    from local_agent.scene_language import OBJECTS, parse_scene_request as compile_prompt

    names = {name for name, _aliases in OBJECTS}
    assert {"snail", "scooter", "bicycle", "fish", "cactus", "snowman", "castle",
            "sofa", "submarine", "coral", "swing", "slide", "mia"} <= names
    underwater = compile_prompt("Создай подводный мир с рыбами, кораллами и подлодкой")
    assert underwater["environment"] == "underwater"
    assert [item["primitive"] for item in underwater["objects"]] == ["fish", "coral", "submarine"]


def test_quoted_title_and_top_down_camera_are_parsed_without_extra_fields():
    from local_agent.scene_language import parse_scene_request as compile_prompt

    plan = compile_prompt('Создай надпись «Привет, мир» на синем кубе, вид сверху')
    assert plan["text_content"] == "Привет, мир"
    assert plan["camera_angle"] == "top"
    assert plan["objects"][0]["primitive"] == "cube"


def test_generated_blender_script_is_valid_python_syntax():
    from local_agent.scene_request import _BLENDER_SCRIPT

    compile(_BLENDER_SCRIPT, "generated_scene_builder.py", "exec")


def test_explicitly_excluded_objects_are_not_added():
    from local_agent.scene_language import parse_scene_request as compile_prompt, SceneRequestError

    plan = compile_prompt("Создай красный куб без деревьев")
    assert [item["primitive"] for item in plan["objects"]] == ["cube"]
    with pytest.raises(SceneRequestError, match="исключены"):
        compile_prompt("Создай лес без деревьев")
