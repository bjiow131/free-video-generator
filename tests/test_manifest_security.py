import pytest

from local_agent.manifest import ProjectManifest


def manifest(**overrides):
    data = {
        "schema_version": 1,
        "project_id": "safe_project-01",
        "project_name": "Fictional test",
        "initial_image": "C:/素材/reference.png",
        "scenes": [{"scene_id": "scene_01", "prompt": "A fictional scene."}],
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize("project_id", ["../outside", "a/b", r"a\b", "..", "x" * 65, "with space"])
def test_rejects_unsafe_project_ids(project_id):
    with pytest.raises(ValueError, match="project_id"):
        ProjectManifest.from_dict(manifest(project_id=project_id))


@pytest.mark.parametrize("scene_id", ["../escape", "nested/scene", r"nested\scene", "space id"])
def test_rejects_unsafe_scene_ids(scene_id):
    with pytest.raises(ValueError, match="scene_id"):
        ProjectManifest.from_dict(manifest(scenes=[{"scene_id": scene_id, "prompt": "A scene"}]))


@pytest.mark.parametrize("duration", [True, 5.5, "5", 0, 121])
def test_rejects_invalid_duration(duration):
    with pytest.raises(ValueError, match="duration_seconds"):
        ProjectManifest.from_dict(manifest(scenes=[{"prompt": "A scene", "duration_seconds": duration}]))


@pytest.mark.parametrize("output_name", ["../x.mp4", r"..\x.mp4", "bad:name.mp4", "trailing.", "movie.mov"])
def test_rejects_unsafe_output_names(output_name):
    with pytest.raises(ValueError, match="output_name"):
        ProjectManifest.from_dict(manifest(output_name=output_name))


def test_rejects_unknown_schema_version():
    with pytest.raises(ValueError, match="schema_version"):
        ProjectManifest.from_dict(manifest(schema_version=2))


@pytest.mark.parametrize("schema_version", [True, 1.0, "1"])
def test_rejects_non_integer_schema_version(schema_version):
    with pytest.raises(ValueError, match="schema_version"):
        ProjectManifest.from_dict(manifest(schema_version=schema_version))


@pytest.mark.parametrize("max_scenes", [True, 0, -1, 1.0, "10"])
def test_rejects_invalid_scene_limit(max_scenes):
    with pytest.raises(ValueError, match="max_scenes"):
        ProjectManifest.from_dict(manifest(), max_scenes=max_scenes)


def test_schema_version_and_project_name_round_trip():
    parsed = ProjectManifest.from_dict(manifest())
    restored = ProjectManifest.from_dict(parsed.to_dict())
    assert restored.project_id == "safe_project-01"
    assert restored.project_name == "Fictional test"
    assert restored.schema_version == 1


@pytest.mark.parametrize("name", ["CON", "aux", "NUL", "COM1", "lpt9"])
def test_windows_device_names_rejected_on_every_host(name):
    with pytest.raises(ValueError):
        ProjectManifest.from_dict(manifest(project_id=name))
    with pytest.raises(ValueError):
        ProjectManifest.from_dict(manifest(scenes=[{"scene_id": name, "prompt": "test"}]))
    with pytest.raises(ValueError):
        ProjectManifest.from_dict(manifest(output_name=name + ".mp4"))
    from local_agent.path_names import path_identifier_pattern
    assert path_identifier_pattern(48).fullmatch(name) is None
    assert path_identifier_pattern(128, dots=True).fullmatch(name + ".json") is None


def test_scene_ids_cannot_alias_on_windows():
    with pytest.raises(ValueError, match="unique"):
        ProjectManifest.from_dict(manifest(scenes=[{"scene_id": "Scene", "prompt": "one"}, {"scene_id": "scene", "prompt": "two"}]))
