from local_agent.prompt_dialogue import extract_quoted_dialogue


def test_extracts_quoted_russian_speech_and_speaker():
    result = extract_quoted_dialogue("Мия идет по тропинке и начинает говорить: «Смотри, улитка!»")
    assert result == [{
        "speaker": "Мия",
        "text": "Смотри, улитка!",
        "delivery": "natural",
    }]


def test_extracts_quoted_singing_lyrics():
    result = extract_quoted_dialogue('Mia starts singing: "La la, little snail!"')
    assert result and result[0]["text"] == "La la, little snail!"


def test_ignores_quotes_without_speech_context():
    assert extract_quoted_dialogue('Мия видит табличку «Лесная тропа» и улыбается.') == []


def test_does_not_invent_text_when_prompt_has_no_quoted_words():
    assert extract_quoted_dialogue("Мия начинает говорить, но слова не указаны.") == []
