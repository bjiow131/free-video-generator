"""Bounded Russian scene-description compiler for Blender Work Agent.

The prompt is parsed as inert text. It is never evaluated as Python or shell.
"""
from __future__ import annotations

import re
from typing import Any

MAX_PROMPT_CHARS = 1200
MAX_OBJECTS = 40

COLORS = (
    ("red", ("красный", "красная", "красное", "красные", "красных", "красную"), (0.80, 0.035, 0.025, 1.0)),
    ("green", ("зелёный", "зеленый", "зелёная", "зеленая", "зелёное", "зеленое", "зелёные", "зеленые", "зелёных", "зеленых"), (0.04, 0.48, 0.12, 1.0)),
    ("blue", ("синий", "синяя", "синее", "синие", "синих", "голубой", "голубая", "голубое"), (0.025, 0.18, 0.85, 1.0)),
    ("yellow", ("жёлтый", "желтый", "жёлтая", "желтая", "жёлтое", "желтое", "жёлтые", "желтые", "жёлтых", "желтых"), (0.95, 0.58, 0.025, 1.0)),
    ("orange", ("оранжевый", "оранжевая", "оранжевое", "оранжевые"), (1.0, 0.22, 0.025, 1.0)),
    ("purple", ("фиолетовый", "фиолетовая", "фиолетовое", "фиолетовые"), (0.38, 0.07, 0.68, 1.0)),
    ("white", ("белый", "белая", "белое", "белые", "белых"), (0.88, 0.88, 0.88, 1.0)),
    ("black", ("чёрный", "черный", "чёрная", "черная", "чёрное", "черное"), (0.025, 0.025, 0.025, 1.0)),
    ("brown", ("коричневый", "коричневая", "коричневое", "коричневые"), (0.28, 0.11, 0.035, 1.0)),
    ("pink", ("розовый", "розовая", "розовое", "розовые"), (0.95, 0.12, 0.42, 1.0)),
    ("gray", ("серый", "серая", "серое", "серые", "серого"), (0.32, 0.35, 0.38, 1.0)),
    ("gold", ("золотой", "золотая", "золотое", "золотые", "золотую", "золотым", "золотых"), (0.83, 0.53, 0.12, 1.0)),
)

# Longer aliases are preferred when multiple names overlap.
OBJECTS = (
    ("uv_sphere", ("сфера", "сферу", "сферы", "сфер", "шар", "шара", "шары", "шаром")),
    ("cube", ("куб", "куба", "кубом", "кубе", "кубы", "кубами", "кубик", "кубики", "блок")),
    ("cylinder", ("цилиндр", "цилиндра", "цилиндры", "труба", "трубу", "трубы")),
    ("cone", ("конус", "конуса", "конусы")),
    ("torus", ("тор", "кольцо", "кольца", "бублик")),
    ("monkey", ("голова обезьяны", "обезьяна", "suzanne", "мэш")),
    ("tree", ("ёлка", "ёлки", "ёлок", "елка", "елки", "елок", "сосна", "сосны", "сосен", "дерево", "деревья", "деревьев", "деревце", "деревьями")),
    ("house", ("дом", "домик", "домики", "домиками", "дома", "домов", "коттедж", "коттеджа", "хижина", "хижину", "изба", "избу", "здание", "здания")),
    ("mountain", ("гора", "горы", "гор", "горный пик", "скала", "скалы")),
    ("cloud", ("облако", "облака", "облаков", "туча", "тучи")),
    ("person", ("человек", "человека", "человечек", "персонаж", "персонажа", "робот", "робота")),
    ("car", ("машина", "машину", "машины", "машин", "автомобиль", "автомобиля", "автомобили", "авто", "автомобилем")),
    ("table", ("стол", "стола", "столы")),
    ("chair", ("стул", "стула", "стулья", "стульев", "кресло", "кресла")),
    ("lamp", ("лампа", "лампу", "фонарь", "фонаря")),
    ("bench", ("скамейка", "скамейку", "скамейкой", "скамью", "лавочка", "лавочкой", "лавку")),
    ("flower", ("цветок", "цветы", "цветка", "цветов")),
    ("grass", ("трава", "траву", "пучок травы")),
    ("rock", ("камень", "камни", "камня", "камней", "валун", "валуны")),
    ("road", ("дорога", "дорогу", "шоссе", "трасса")),
    ("fence", ("забор", "ограда", "изгородь")),
    ("bed", ("кровать", "кровати")),
    ("book", ("книга", "книгу", "книги")),
    ("mug", ("кружка", "кружку", "чашка", "чашку")),
    ("bottle", ("бутылка", "бутылку", "бутылки")),
    ("smartphone", ("телефон", "смартфон", "смартфона")),
    ("rocket", ("ракета", "ракету", "ракеты")),
    ("sun", ("солнце", "солнца")),
    ("moon", ("луна", "месяц")),
    ("star", ("звезда", "звёзды", "звезды", "звезду")),
    ("snail", ("улитка", "улитку", "улитки", "улиток", "улиткой")),
    ("scooter", ("самокат", "самоката", "самокаты", "самокате")),
    ("bicycle", ("велосипед", "велосипеда", "велосипеды", "велосипеде", "велосипедом")),
    ("fish", ("рыба", "рыбу", "рыбы", "рыбка", "рыбку", "рыбки", "рыбами")),
    ("cactus", ("кактус", "кактуса", "кактусы")),
    ("snowman", ("снеговик", "снеговика", "снеговики", "снеговиками")),
    ("castle", ("замок", "замка", "замки", "крепость")),
    ("sofa", ("диван", "дивана", "диваны")),
    ("submarine", ("подлодка", "подлодкой", "подводная лодка", "субмарина")),
    ("coral", ("коралл", "кораллы", "кораллами")),
    ("swing", ("качели", "качель", "качелями")),
    ("slide", ("горка", "горку", "горки", "горкой")),
    ("mia", ("мия",)),
    ("person", ("девочка", "девочку", "девочки", "девушка", "девушку", "девушки")),

)

COUNT_WORDS = {
    "один": 1, "одна": 1, "одно": 1, "два": 2, "две": 2, "три": 3,
    "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8,
    "девять": 9, "десять": 10,
}
COUNT_TOKEN = r"(?:\d{1,2}|" + "|".join(COUNT_WORDS) + r")"
COUNT_RE = re.compile(r"(?<![а-яё\w])(" + COUNT_TOKEN + r")(?![а-яё\w])")
SIZE_RE = re.compile(r"(?:размер(?:ом)?|масштаб(?:ом)?)\s*(?:=\s*)?(\d+(?:[.,]\d+)?)")

class SceneRequestError(ValueError):
    """A natural-language scene request is unsupported or unsafe."""


def _has(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def _count(token: str) -> int:
    return int(token) if token.isdigit() else COUNT_WORDS[token]


def parse_scene_request(prompt: str) -> dict[str, Any]:
    """Compile natural Russian scene instructions into a bounded inert plan."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise SceneRequestError(f"Задание должно содержать от 1 до {MAX_PROMPT_CHARS} символов.")
    text = re.sub(r"\s+", " ", prompt.casefold()).strip()
    quoted = re.search(r'[«"]([^»"]{1,100})[»"]', prompt)
    text_content = quoted.group(1).strip() if quoted else ""
    masked = re.sub(r"\d+\s*:\s*\d+", lambda m: " " * len(m.group(0)), text)
    masked = SIZE_RE.sub(lambda m: " " * len(m.group(0)), masked)

    found: list[tuple[int, int, str, str]] = []
    for kind, aliases in OBJECTS:
        for alias in aliases:
            for match in re.finditer(r"(?<![а-яё\w])" + re.escape(alias) + r"(?![а-яё\w])", masked):
                found.append((match.start(), match.end(), kind, alias))
    found.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    selected: list[tuple[int, int, str, str]] = []
    for item in found:
        preceding = masked[max(0, item[0] - 55):item[0]]
        if re.search(r"(?:без|не\\s+(?:добавляй|добавить|создавай|создать|делай|делать))\\s+(?:[а-яё-]+\\s+){0,2}$", preceding):
            continue
        if selected and item[0] < selected[-1][1]:
            continue
        selected.append(item)
    if not selected:
        # Scene-only prompts are useful too: infer a small starter composition.
        if _has(text, "лес", "роща", "лесной"):
            default_kind = "tree"
        elif _has(text, "подводный мир", "под водой", "океанариум"):
            default_kind = "fish"
        elif _has(text, "пустын", "сахара"):
            default_kind = "cactus"
        elif _has(text, "зим", "снег", "снежный"):
            default_kind = "snowman"
        elif _has(text, "деревн", "посёлок", "поселок"):
            default_kind = "house"
        elif _has(text, "площадк", "детская площадка"):
            default_kind = "swing"
        elif _has(text, "фэнтези", "сказоч", "волшебный мир"):
            default_kind = "castle"
        elif text_content or _has(text, "надпись", "логотип", "текст"):
            default_kind = "cube"
        elif _has(text, "город", "улица", "городской"):
            default_kind = "house"
        elif _has(text, "космос", "галактик", "звёздное небо", "звездное небо"):
            default_kind = "rocket"
        elif _has(text, "горы", "горный пейзаж", "долина", "скалы", "пейзаж", "природа"):
            default_kind = "mountain"
        elif _has(text, "остров", "пляж", "море", "океан"):
            default_kind = "tree"
        elif _has(text, "комнат", "интерьер", "гостиная"):
            default_kind = "table"
        elif _has(text, "студия", "предметная съёмка", "предметная съемка"):
            default_kind = "uv_sphere"
        else:
            supported = ", ".join(kind for kind, _aliases in OBJECTS)
            raise SceneRequestError("Не распознан объект или тип сцены. Добавь понятный объект либо опиши лес, город, космос, горы, остров, комнату или студию. Каталог объектов: " + supported + ".")
        selected = [(0, 0, default_kind, default_kind)]

    size_match = SIZE_RE.search(text)
    scale = float(size_match.group(1).replace(",", ".")) if size_match else (1.7 if _has(text, "больш") else 0.6 if _has(text, "малень") else 1.0)
    if not 0.1 <= scale <= 10:
        raise SceneRequestError("Масштаб должен быть от 0.1 до 10.")

    objects: list[dict[str, Any]] = []
    previous_end = 0
    global_count_match = re.match(r"^(" + COUNT_TOKEN + r")\b", masked)
    global_count = _count(global_count_match.group(1)) if global_count_match else None
    for pos, end, kind, _alias in selected:
        prefix = masked[max(previous_end, pos - 70):pos]
        counts = list(COUNT_RE.finditer(prefix))
        count = _count(counts[-1].group(1)) if counts else (global_count if not objects and global_count else 1)
        if count < 1 or count > MAX_OBJECTS or len(objects) + count > MAX_OBJECTS:
            raise SceneRequestError(f"В одной сцене допускается не более {MAX_OBJECTS} основных объектов.")
        segment = text[previous_end:pos]
        color_name, rgba = "blue", (0.22, 0.42, 0.68, 1.0)
        # Choose the last color adjective in the phrase immediately before the object.
        last_color = (-1, None)
        for candidate, aliases, color in COLORS:
            for word in aliases:
                match = re.search(r"(?<![а-яё])" + re.escape(word) + r"(?![а-яё])", segment)
                if match and match.start() > last_color[0]:
                    last_color = (match.start(), (candidate, color))
        if last_color[1]:
            color_name, rgba = last_color[1]
        else:
            defaults = {
                "tree": ("green", (0.055, 0.31, 0.09, 1.0)),
                "house": ("brown", (0.42, 0.24, 0.12, 1.0)),
                "mountain": ("gray", (0.30, 0.34, 0.38, 1.0)),
                "cloud": ("white", (0.88, 0.90, 0.94, 1.0)),
                "person": ("orange", (0.85, 0.25, 0.08, 1.0)),
                "car": ("red", (0.80, 0.035, 0.025, 1.0)),
                "grass": ("green", (0.055, 0.31, 0.09, 1.0)),
                "rock": ("gray", (0.32, 0.35, 0.38, 1.0)),
                "road": ("gray", (0.15, 0.16, 0.18, 1.0)),
                "flower": ("pink", (0.95, 0.12, 0.42, 1.0)),
                "sun": ("yellow", (0.95, 0.58, 0.025, 1.0)),
                "moon": ("white", (0.88, 0.88, 0.82, 1.0)),
                "star": ("gold", (0.83, 0.53, 0.12, 1.0)),
                "table": ("brown", (0.28, 0.11, 0.035, 1.0)),
                "chair": ("brown", (0.28, 0.11, 0.035, 1.0)),
                "snail": ("orange", (0.78, 0.34, 0.08, 1.0)),
                "scooter": ("yellow", (0.95, 0.58, 0.025, 1.0)),
                "bicycle": ("red", (0.80, 0.035, 0.025, 1.0)),
                "fish": ("orange", (1.0, 0.30, 0.06, 1.0)),
                "cactus": ("green", (0.055, 0.31, 0.09, 1.0)),
                "snowman": ("white", (0.88, 0.90, 0.94, 1.0)),
                "castle": ("gray", (0.42, 0.45, 0.50, 1.0)),
                "sofa": ("purple", (0.38, 0.07, 0.68, 1.0)),
                "submarine": ("yellow", (0.95, 0.58, 0.025, 1.0)),
                "coral": ("pink", (0.95, 0.12, 0.42, 1.0)),
                "swing": ("blue", (0.025, 0.18, 0.85, 1.0)),
                "slide": ("red", (0.80, 0.035, 0.025, 1.0)),
                "mia": ("orange", (0.85, 0.25, 0.08, 1.0)),
            }
            color_name, rgba = defaults.get(kind, (color_name, rgba))
        for _ in range(count):
            objects.append({
                "primitive": kind, "color_name": color_name, "color": list(rgba),
                "scale": scale, "name": f"{kind.replace('_', ' ').title()} {len(objects) + 1:02d}",
            })
        previous_end = end

    if "9:16" in text or _has(text, "вертикаль", "портрет", "shorts", "reels", "клип"):
        aspect, resolution = "9:16", [720, 1280]
    elif "1:1" in text or _has(text, "квадрат"):
        aspect, resolution = "1:1", [1024, 1024]
    elif "4:3" in text:
        aspect, resolution = "4:3", [1024, 768]
    elif "3:2" in text:
        aspect, resolution = "3:2", [1200, 800]
    else:
        aspect, resolution = "16:9", [1280, 720]

    if _has(text, "лес", "лесной", "лесная", "роща"):
        environment = "forest"
    elif _has(text, "комнат", "интерьер", "внутри дома", "гостиная"):
        environment = "room"
    elif _has(text, "город", "улица", "городской", "небоскрёб", "небоскреб"):
        environment = "city"
    elif _has(text, "космос", "космический", "галактик", "звёздное небо", "звездное небо"):
        environment = "space"
    elif _has(text, "остров", "пляж", "море", "океан"):
        environment = "island"
    elif _has(text, "горы", "горный пейзаж", "долина", "пейзаж", "природа"):
        environment = "mountains"
    elif _has(text, "подводный мир", "под водой", "океанариум"):
        environment = "underwater"
    elif _has(text, "пустын", "сахара"):
        environment = "desert"
    elif _has(text, "зим", "снег", "снежный"):
        environment = "winter"
    elif _has(text, "деревн", "посёлок", "поселок"):
        environment = "village"
    elif _has(text, "площадк", "детская площадка"):
        environment = "playground"
    elif _has(text, "фэнтези", "сказоч", "волшебный мир"):
        environment = "fantasy"
    elif _has(text, "студия", "предметная съёмка", "предметная съемка", "на подиуме"):
        environment = "studio"
    else:
        environment = "auto"

    if _has(text, "low poly", "лоу-поли", "лоуполи", "низкополигон"):
        style = "low_poly"
    elif _has(text, "мультяш", "мультфильм", "cartoon", "для детей"):
        style = "cartoon"
    elif _has(text, "реалист", "фотореал", "realistic"):
        style = "realistic"
    elif _has(text, "минимал", "минимализм"):
        style = "minimal"
    else:
        style = "balanced"

    if _has(text, "ночь", "ночной", "ночная", "луна", "звёздное небо", "звездное небо"):
        lighting = "night"
    elif _has(text, "закат", "закатный", "золотой час"):
        lighting = "sunset"
    elif _has(text, "драматич", "контров", "киношн", "cinematic"):
        lighting = "cinematic"
    else:
        lighting = "soft"

    if _has(text, "по кругу", "кругом", "кольцом"):
        layout = "circle"
    elif _has(text, "сеткой", "по сетке", "таблицей"):
        layout = "grid"
    elif _has(text, "в ряд", "в линию", "по прямой", "рядом", "слева направо"):
        layout = "line"
    else:
        layout = "auto"

    render_percentage = 100 if _has(text, "максимальное качество", "100%", "финальный рендер") else 75 if _has(text, "высокое качество", "детально", "4k", "8k") else 50
    animation = {
        "enabled": _has(text, "анимируй", "анимация", "движется", "движение", "вращается", "вращающ", "крутится", "крутящ", "прыгает", "летит", "едет", "идёт", "идет"),
        "kind": "rotate" if _has(text, "вращается", "вращающ", "крутится", "крутящ", "вращение") else "move" if _has(text, "движется", "движение", "летит", "едет", "идёт", "идет") else "bounce",
        "frames": 96 if _has(text, "4 секунды", "4 сек") else 144 if _has(text, "6 секунд", "6 сек") else 120,
    }
    return {
        "schema_version": 2, "objects": objects, "resolution": resolution, "aspect_ratio": aspect,
        "render_percentage": render_percentage, "prompt_summary": prompt.strip(), "environment": environment,
        "style": style, "lighting": lighting, "layout": layout, "animation": animation,
        "ground": not _has(text, "без пола", "без земли", "без подставки", "прозрачный фон"),
        "transparent_background": _has(text, "прозрачный фон", "альфа-канал"),
        "world_color": [0.008, 0.012, 0.025, 1.0] if lighting == "night" else [0.055, 0.055, 0.055, 1.0],
        "text_content": text_content,
        "camera_angle": "top" if _has(text, "вид сверху", "камера сверху", "сверху вниз") else "auto",
    }
