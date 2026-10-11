"""Strict, offline Russian command interpreter. Returns data, never Blender code.

Only a documented subset is supported. In particular, an image reference is not
an armature, and an inferred action never becomes a generic demonstration.
"""
from __future__ import annotations

import re
from typing import Any

MAX_PROMPT = 3000
_ACTIONS = (
    ("speak", r"\b(?:говор\w*|произн\w*|по[её]т|петь|сказал\w*|разговар\w*)\b"),
    ("wave", r"\b(?:машет|помах\w*|махн\w*)\b"),
    ("turn", r"\b(?:поворач\w*|поверн\w*|разворач\w*)\b"),
    ("walk", r"\b(?:ид[её]т|идти|идут|шаг\w*|гуля\w*|проход\w*)\b"),
    ("idle", r"\b(?:сто[иия]\w*|жд[её]т|замер\w*)\b"),
)
_UNSUPPORTED = (
    ("ride", r"\b(?:едет|ката\w*|велосипед\w*|самокат\w*)\b", "Нужна совместимая модель транспорта и анимация езды"),
    ("pick", r"\b(?:бер[её]т|поднима\w*|хвата\w*|броса\w*)\b", "Нужны риг рук и привязка реквизита"),
    ("run", r"\b(?:беж\w*|бега\w*|прыга\w*)\b", "Нужна анимация бега или прыжка"),
)
_CAMERA = (("follow", r"\b(?:след\w*|сопровожда\w*|за ним|за ней)\b"),
           ("push_in", r"\b(?:приближа\w*|наезжа\w*|зум\w*)\b"),
           ("hold", r"\b(?:неподвиж\w*|статич\w*|фиксирован\w*)\b"))


class PromptError(ValueError):
    """The requested behavior has no safe deterministic representation."""


def _name_match(text: str, name: str) -> bool:
    return bool(name.strip() and re.search(r"(?<!\w)" + re.escape(name.casefold().replace("ё", "е")) + r"(?!\w)", text.casefold().replace("ё", "е")))


def interpret_scene(prompt: str, state: dict[str, Any], scene_id: str) -> dict[str, Any]:
    """Return one explicit, validated scene plan with actionable prerequisites.

    Fixture requires *explicit* words 'тестовый персонаж' / 'test actor'.
    Real actors require ``assets/<id>.blend`` and rig validation at execution.
    """
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= MAX_PROMPT:
        raise PromptError("Описание сцены должно содержать 1–3000 символов")
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,47}", scene_id):
        raise PromptError("Недопустимый идентификатор сцены")
    if not isinstance(state, dict) or not isinstance(state.get("characters"), list) or not isinstance(state.get("settings"), dict):
        raise PromptError("Некорректное состояние проекта")
    text = prompt.casefold().replace("ё", "е")
    fixture = bool(re.search(r"\b(?:тестов\w* персонаж\w*|test actor)\b", text))
    found = [ch for ch in state["characters"] if isinstance(ch, dict) and isinstance(ch.get("name"), str) and _name_match(text, ch["name"])]
    if fixture and found:
        raise PromptError("Нельзя смешивать тестового персонажа с паспортом реального героя")
    if len(found) > 1:
        raise PromptError("В этой версии можно анимировать одного персонажа в сцене. Разделите действия")
    if not fixture and not found:
        raise PromptError("Укажите имя персонажа из паспорта или слова «тестовый персонаж» для проверки движка")
    actor_id = "__fixture__" if fixture else found[0].get("id")
    if not isinstance(actor_id, str) or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]{0,47}", actor_id):
        raise PromptError("Некорректный ID персонажа")
    unsupported = [reason for _, expr, reason in _UNSUPPORTED if re.search(expr, text)]
    # Do not transform a prompt with unsupported actions into a generic walk.
    occurrences = []
    for action, expr in _ACTIONS:
        for hit in re.finditer(expr, text):
            occurrences.append((hit.start(), action))
    occurrences.sort(key=lambda item: item[0])
    actions = []
    for _, action in occurrences:
        if not actions or actions[-1] != action:
            actions.append(action)
    if not actions and not unsupported:
        raise PromptError("Не распознано действие. Поддерживаются: идёт, поворачивается, машет, говорит, стоит")
    # Camera is a user choice; explicit text takes precedence over settings.
    camera = "follow" if "walk" in actions else "hold"
    for mode, expr in _CAMERA:
        if re.search(expr, text):
            camera = mode
            break
    cfg = state["settings"]
    duration, fps = cfg.get("duration"), cfg.get("fps")
    if isinstance(duration, bool) or not isinstance(duration, int) or not 1 <= duration <= 120:
        raise PromptError("Недопустимая длительность")
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 60:
        raise PromptError("Недопустимая частота кадров")
    resolution = cfg.get("resolution")
    if resolution not in {"360x640", "640x360", "512x512", "720x1280", "1280x720"}:
        raise PromptError("Неподдерживаемое разрешение")
    if "сцена" in text and re.search(r"\bсцен[аыеу]\s*[2-9]\b", text):
        raise PromptError("Многосценный текст пока не разбирается одной командой: создайте сцены по очереди")
    if not actions:
        actions = ["idle"]
    if "speak" in actions and not re.search(r"(?:говор\w*|произн\w*|по[её]т|петь|разговар\w*|сказал\w*)", text):
        raise PromptError("Неясная команда речи")
    requirements = list(dict.fromkeys(unsupported))
    if not fixture:
        requirements.append(f"Нужен локальный assets/{actor_id}.blend с объектом STUDIO_ACTOR")
        if "walk" in actions or "wave" in actions:
            requirements.append("Для ходьбы/жестов необходим совместимый риг и анимация; пока не исполняются для реальных моделей")
        if "speak" in actions:
            requirements.append("Для речи требуется shape key MouthOpen; пока не исполняется для реальных моделей")
    result = {
        "schema_version": 1,
        "scene_id": scene_id,
        "prompt": prompt.strip(),
        "actor_id": actor_id,
        "actor_kind": "procedural_test_fixture" if fixture else "project_character",
        "actions": actions,
        "camera": camera,
        "duration": duration,
        "fps": fps,
        "resolution": resolution,
        "readiness": "ready_fixture" if not requirements and fixture else "missing_requirements",
        "missing_requirements": requirements,
        "label": "ТЕСТОВЫЙ ПЕРСОНАЖ — НЕ МИЯ И НЕ ГОТОВАЯ 3D-МОДЕЛЬ" if fixture else found[0]["name"],
    }
    return result
