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
    assert plan["animation"]["frames"] == 120
    assert plan["render_percentage"] == 75


def test_catalog_includes_every_supported_composite_family():
    from local_agent.scene_language import OBJECTS

    names = {name for name, _aliases in OBJECTS}
    assert {"tree", "house", "mountain", "cloud", "person", "car", "table", "chair",
            "lamp", "bench", "flower", "grass", "rock", "road", "fence", "bed",
            "book", "mug", "bottle", "smartphone", "rocket", "sun", "moon", "star"} <= names


def test_character_identity_is_not_hardcoded_in_scene_language():
    from local_agent.scene_language import OBJECTS, parse_scene_request as compile_prompt

    names = {name for name, _aliases in OBJECTS}
    assert "mia" not in names
    plan = compile_prompt("Создай жёлтый самокат рядом с улиткой, мультяшный стиль, 9:16")
    assert [item["primitive"] for item in plan["objects"]] == ["scooter", "snail"]
    assert plan["style"] == "cartoon"
    assert plan["aspect_ratio"] == "9:16"


def test_thematic_scene_catalog_includes_additional_families():
    from local_agent.scene_language import OBJECTS, parse_scene_request as compile_prompt

    names = {name for name, _aliases in OBJECTS}
    assert {"snail", "scooter", "bicycle", "fish", "cactus", "snowman", "castle",
            "sofa", "submarine", "coral", "swing", "slide", "person"} <= names
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


def test_explicit_resolution_presets_are_respected():
    from local_agent.scene_language import parse_scene_request as compile_prompt

    full_hd = compile_prompt("Создай красный куб, Full HD, 16:9")
    vertical_4k = compile_prompt("Создай ракету, 4K, вертикально 9:16")
    assert full_hd["resolution"] == [1920, 1080]
    assert full_hd["render_percentage"] == 100
    assert vertical_4k["resolution"] == [2160, 3840]
    assert vertical_4k["render_percentage"] == 100

def test_riding_scooter_relationship_is_generic_and_bound_to_selected_card():
    from local_agent.scene_language import parse_scene_request as compile_prompt
    from local_agent.scene_request import _append_character_cards

    plan = _append_character_cards(compile_prompt("Бобик едет на самокате по лесу, вертикально 9:16"), [
        {"id": "bobik-card", "name": "Бобик", "description": "Собака", "references": []},
    ], "Бобик едет на самокате по лесу, вертикально 9:16")
    assert plan["relationships"]["character_riding_scooter"] == "bobik-card"
    assert plan["environment"] == "forest"
    assert plan["animation"]["enabled"] is True


def test_selected_character_cards_are_added_once_and_keep_reference_paths():
    from local_agent.scene_language import parse_scene_request
    from local_agent.scene_request import _append_character_cards

    plan = parse_scene_request("Мия едет на самокате по лесу, вертикально 9:16")
    card = {
        "id": "mia-card",
        "name": "Мия",
        "description": "Бирюзовый комбинезон и розовый рюкзак",
        "references": ["C:/BlenderAgentLibrary/mia-card/01_front.png", "C:/BlenderAgentLibrary/mia-card/02_side.jpg"],
        "reference_labels": {"C:/BlenderAgentLibrary/mia-card/01_front.png": "Фронт", "C:/BlenderAgentLibrary/mia-card/02_side.jpg": "Профиль справа"},
    }
    result = _append_character_cards(plan, [card])
    assert len([obj for obj in result["objects"] if obj.get("character_card_id") == "mia-card"]) == 1
    assert result["selected_characters"][0]["id"] == "mia-card"
    assert result["selected_characters"][0]["references"] == card["references"]
    assert result["selected_characters"][0]["reference_labels"] == card["reference_labels"]


def test_multiple_selected_characters_are_added_as_separate_scene_objects():
    from local_agent.scene_language import parse_scene_request
    from local_agent.scene_request import _append_character_cards

    plan = _append_character_cards(parse_scene_request("Два героя в лесу"), [
        {"id": "mia", "name": "Мия", "description": "Девочка", "references": []},
        {"id": "fox", "name": "Лисёнок", "description": "Рыжий лисёнок, друг Мии", "references": []},
    ])
    assert [obj["name"] for obj in plan["objects"] if obj.get("character_card_id")] == ["Мия", "Лисёнок"]
    assert [item["name"] for item in plan["selected_characters"]] == ["Мия", "Лисёнок"]
    fox = next(obj for obj in plan["objects"] if obj.get("character_card_id") == "fox")
    assert fox["primitive"] == "person"


def test_manually_selected_character_is_linked_to_scooter_action_without_name_in_prompt():
    from local_agent.scene_language import parse_scene_request
    from local_agent.scene_request import _append_character_cards

    plan = _append_character_cards(parse_scene_request("Едет на самокате по лесу, вертикально 9:16"), [
        {"id": "bobik-card", "name": "Бобик", "description": "Собака", "references": []},
    ], "Едет на самокате по лесу, вертикально 9:16")
    assert plan["relationships"]["character_riding_scooter"] == "bobik-card"


def test_reference_numbers_are_selected_per_character_card():
    from local_agent.scene_language import parse_scene_request
    from local_agent.scene_request import _append_character_cards

    prompt = "Мия — референсы №2 и №3; Степа — референс №1. Они встречаются на лесной тропе."
    cards = [
        {"id": "mia", "name": "Мия", "description": "", "references": ["mia1.png", "mia2.png", "mia3.png"]},
        {"id": "stepa", "name": "Степа", "description": "", "references": ["stepa1.png", "stepa2.png"]},
    ]
    plan = _append_character_cards(parse_scene_request("Два персонажа в лесу"), cards, prompt)
    by_id = {item["id"]: item for item in plan["selected_characters"]}
    assert by_id["mia"]["reference_indices"] == [2, 3]
    assert by_id["stepa"]["reference_indices"] == [1]


def test_character_profile_category_selects_generic_animal_blockout():
    from local_agent.scene_language import parse_scene_request
    from local_agent.scene_request import _append_character_cards

    plan = _append_character_cards(parse_scene_request("Создай лесную поляну"), [
        {
            "id": "bobik", "name": "Бобик", "kind": "Персонаж",
            "profile_type": "Животное", "visual_style": "Стилизованный 3D",
            "description": "Небольшая коричневая собака с длинными ушами",
            "references": ["C:/library/bobik/01_front.png"],
        },
    ], "Бобик стоит на лесной поляне, референс №1")
    bobik = next(obj for obj in plan["objects"] if obj.get("character_card_id") == "bobik")
    assert bobik["primitive"] == "animal"
    assert bobik["profile_type"] == "Животное"
    assert plan["selected_characters"][0]["reference_indices"] == [1]


def test_scene_plan_describes_coastal_bicycle_action_and_camera_limitations():
    from local_agent.scene_language import parse_scene_request as compile_prompt
    from local_agent.scene_request import _append_character_cards

    prompt = "Мия едет на велосипеде по дорожке возле моря, 8 секунд, вертикально 9:16"
    parsed = compile_prompt(prompt)
    assert parsed["environment"] == "coast"
    assert parsed["relationships"]["character_riding_bicycle"] is True
    assert parsed["animation"]["enabled"] is True
    plan = _append_character_cards(parsed, [
        {"id": "mia-card", "name": "Мия", "description": "Девочка", "references": []},
    ], prompt)["scene_plan"]
    assert plan["duration_seconds"] == 8
    assert "ocean_surface" in plan["location"]["environment_assets"]
    assert "cycling_path" in plan["location"]["environment_assets"]
    assert plan["action_steps"][0]["action"] == "ride_vehicle"
    assert plan["action_steps"][0]["status"] == "partial_blockout"
    assert plan["camera"]["motion"] == "follow_actor"
    assert plan["camera"]["status"] == "basic_linear_follow"
    assert "linear X-axis" in plan["camera"]["limitation"]


def test_scene_plan_is_generic_and_keeps_character_identity_from_card():
    from local_agent.scene_planner import build_scene_plan

    plan = build_scene_plan(
        "Бобик идёт по лесной тропе",
        [{"name": "Бобик", "primitive": "animal", "character_card_id": "bobik-card",
          "profile_type": "Животное"}],
        "forest", {"enabled": True, "kind": "move", "frames": 150}, {},
    )
    assert plan["actors"][0]["id"] == "bobik-card"
    assert plan["location"]["environment_id"] == "forest"
    assert plan["camera"]["motion"] == "static"
