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
