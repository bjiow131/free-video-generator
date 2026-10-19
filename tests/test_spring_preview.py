from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from local_agent.spring_preview import (
    SpringPreviewError, find_spring_donor, render_spring_preview,
)


def test_finds_only_hash_pinned_spring_filename(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    donor_dir = workspace / "donors" / "spring"
    donor_dir.mkdir(parents=True)
    donor = donor_dir / "spring.blend"
    donor.write_bytes(b"fixture spring donor")
    digest = hashlib.sha256(donor.read_bytes()).hexdigest()
    assert find_spring_donor(workspace, expected_sha256=digest) == donor


def test_rejects_same_name_with_wrong_hash(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    donor = workspace / "spring.blend"
    donor.write_bytes(b"not the pinned donor")
    assert find_spring_donor(workspace) is None


def test_does_not_follow_symlink_directory(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    donor = outside / "spring.blend"
    donor.write_bytes(b"fixture spring donor")
    digest = hashlib.sha256(donor.read_bytes()).hexdigest()
    link = workspace / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    assert find_spring_donor(workspace, expected_sha256=digest) is None


def test_rejects_workspace_symlink(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "workspace_link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(SpringPreviewError, match="workspace_not_a_regular_directory"):
        find_spring_donor(link)


def test_rejects_invalid_project_name_before_local_execution(monkeypatch):
    monkeypatch.delenv("LOCAL_AGENT_WORKSPACE", raising=False)
    result = render_spring_preview("../outside")
    assert result == {"status": "rejected", "reason": "invalid_project_name"}


def test_blocks_when_pinned_donor_is_not_in_workspace(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    blender = tmp_path / "blender.exe"
    blender.touch()
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(workspace))
    monkeypatch.setattr("local_agent.spring_preview.find_blender_executable",
                        lambda: blender)
    assert render_spring_preview("spring_preview_test") == {
        "status": "blocked", "reason": "pinned_spring_donor_not_found"
    }


def test_blocks_existing_output_without_overwriting(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "spring_preview_test").mkdir()
    blender = tmp_path / "blender.exe"
    blender.touch()
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(workspace))
    monkeypatch.setattr("local_agent.spring_preview.find_blender_executable",
                        lambda: blender)
    assert render_spring_preview("spring_preview_test") == {
        "status": "blocked", "reason": "output_already_exists"
    }
