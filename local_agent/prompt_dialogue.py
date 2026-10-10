"""Conservative extraction of explicitly quoted dialogue from scene prompts."""
from __future__ import annotations
import re
from typing import Any

_SPEECH = re.compile(
    r"\b(?:говорит|сказать|сказал(?:а|и)?|произносит|произнести|начинает\s+(?:говорить|произносить|петь)|"
    r"начинает\s+говорить|по[её]т|петь|говорит|says|say|speaks|speak|starts\s+speaking|begins\s+to\s+speak|starts\s+singing|begins\s+singing|sings|sing)\b",
    re.IGNORECASE,
)
_QUOTES = re.compile(r"[«“\"](.*?)[»”\"]", re.DOTALL)
_SPEAKER_BEFORE = re.compile(
    r"([A-ZА-ЯЁ][\w-]{1,39})(?:\s+[\w-]+){0,5}?\s+"
    r"(?:ид[её]т.{0,35}?и\s+)?(?:начинает\s+(?:говорить|произносить|петь)|говорит|произносит|по[её]т|says|speaks|starts\s+singing|begins\s+singing|sings)\b",
    re.IGNORECASE,
)


def extract_quoted_dialogue(prompt: str, *, fallback_speaker: str = "Character") -> list[dict[str, Any]]:
    """Return explicit quoted speech only when nearby prompt wording indicates speaking."""
    if not isinstance(prompt, str) or not prompt.strip() or not _SPEECH.search(prompt):
        return []
    lines = []
    for match in _QUOTES.finditer(prompt):
        text = match.group(1).strip()
        if not text or len(text) > 700:
            continue
        # A quote must be close to a speech verb; avoid treating arbitrary quoted
        # names/titles elsewhere in a long prompt as dialogue.
        nearby = prompt[max(0, match.start() - 180):min(len(prompt), match.end() + 80)]
        if not _SPEECH.search(nearby):
            continue
        before = prompt[:match.start()]
        candidates = list(_SPEAKER_BEFORE.finditer(before[-220:]))
        speaker = candidates[-1].group(1) if candidates else fallback_speaker
        lines.append({"speaker": speaker, "text": text, "delivery": "natural"})
        if len(lines) >= 30:
            break
    return lines
