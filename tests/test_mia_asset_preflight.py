from pathlib import Path

import pytest

from local_agent.mia_asset_preflight import _resolve_workspace_asset


def test_resolves_workspace_relative_blend(tmp_path):
    asset = tmp_path / "MIA_REFERENCE_REVIEW" / "prototype" / "mia.blend"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"fake blend")
    assert _resolve_workspace_asset(tmp_path.resolve(), "MIA_REFERENCE_REVIEW/prototype/mia.blend") == asset.resolve()


@pytest.mark.parametrize("relative", [
    "../outside.blend",
    "folder/../outside.blend",
    "/outside.blend",
    "C:/outside.blend",
    "folder\\outside.blend",
    "folder//mia.blend",
    "folder/not-a-blend.txt",
])
def test_rejects_unsafe_or_non_blend_paths(tmp_path, relative):
    with pytest.raises(ValueError):
        _resolve_workspace_asset(tmp_path.resolve(), relative)


def test_rejects_symlink_component(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (outside / "mia.blend").write_bytes(b"fake blend")
    link = tmp_path / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available")
    with pytest.raises(ValueError, match="invalid_or|link"):
        _resolve_workspace_asset(tmp_path.resolve(), "linked/mia.blend")



def test_preflight_wrapper_keeps_source_unchanged_and_hides_absolute_path(tmp_path, monkeypatch):
    import hashlib
    import json
    from types import SimpleNamespace

    import local_agent.mia_asset_preflight as module

    workspace = tmp_path / "workspace"
    source = workspace / "MIA_REFERENCE_REVIEW" / "prototype" / "mia.blend"
    source.parent.mkdir(parents=True)
    original = b"mock blend payload"
    source.write_bytes(original)
    fake_blender = tmp_path / "blender.exe"
    fake_blender.write_bytes(b"test executable placeholder")
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(workspace))
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(fake_blender))

    def fake_run(command, **kwargs):
        assert command[command.index("--") - 1] == "--python"
        assert "--disable-autoexec" in command
        source_arg, report_arg = command[-2:]
        assert Path(source_arg) == source.resolve()
        Path(report_arg).write_text(json.dumps({
            "status": "completed",
            "source_file_name": "mia.blend",
            "saved_or_modified": False,
            "object_count": 1,
            "objects": [],
        }), encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    result = module.run_mia_asset_preflight(
        "MIA_REFERENCE_REVIEW/prototype/mia.blend",
        "passport-test-001",
    )

    assert result["status"] == "completed"
    assert result["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert result["passport"]["source_file_name"] == "mia.blend"
    assert result["passport"]["saved_or_modified"] is False
    assert str(workspace) not in json.dumps(result)
    assert source.read_bytes() == original
