from local_agent.blender_knowledge import list_topics, search_knowledge


def test_topics_are_available_and_have_unique_ids():
    topics = list_topics()
    assert len(topics) >= 10
    ids = [topic["id"] for topic in topics]
    assert len(ids) == len(set(ids))


def test_russian_query_finds_rigging_guidance():
    results = search_knowledge("риггинг кости веса", limit=5)
    assert results
    assert any("armature" in result["id"] or "weight" in result["id"] for result in results)


def test_render_query_returns_validation_checks():
    results = search_knowledge("black render camera output", limit=5)
    assert results
    assert any("render" in result["id"] or "camera" in result["id"] for result in results)
    assert all(result["verify"] for result in results)


def test_query_and_limit_are_bounded():
    assert search_knowledge("") == []
    assert search_knowledge(None) == []
    assert len(search_knowledge("Blender render", limit=1000)) <= 10
