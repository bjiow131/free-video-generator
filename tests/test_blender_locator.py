"""Windows-targeted tests for local Blender discovery and safe batch arguments."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from local_agent import blender_cli, blender_locator, cli


def _installation(root: Path, release: str) -> Path:
    executable = root / "Blender Foundation" / f"Blender {release}" / "blender.exe"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"fake executable")
    return executable


def test_finds_highest_installed_blender_version_without_52_assumption(tmp_path):
    program_files = tmp_path / "Program Files"
    older = _installation(program_files, "4.5")
    newer = _installation(program_files, "5.0")
    selected = blender_locator.find_blender_executable(
        environ={"PROGRAMFILES": str(program_files)},
        windows=True,
        which=lambda _: None,
    )
    assert selected == newer.resolve()
    assert selected != older.resolve()


def test_finds_installed_blender_from_second_program_files_root(tmp_path):
    one = tmp_path / "Program Files"
    two = tmp_path / "Program Files (x86)"
    older = _installation(one, "4.5")
    newer = _installation(two, "5.1")
    selected = blender_locator.find_blender_executable(
        environ={"PROGRAMFILES": str(one), "PROGRAMFILES(X86)": str(two)},
        windows=True,
        which=lambda _: None,
    )
    assert selected == newer.resolve()
    assert selected != older.resolve()


def test_explicit_executable_overrides_automatic_discovery(tmp_path):
    root = tmp_path / "Program Files"
    auto = _installation(root, "5.2")
    configured = tmp_path / "custom" / "blender.exe"
    configured.parent.mkdir()
    configured.write_bytes(b"fake")
    selected = blender_locator.find_blender_executable(
        environ={"BLENDER_EXECUTABLE": str(configured), "PROGRAMFILES": str(root)},
        windows=True, which=lambda _: str(auto),
    )
    assert selected == configured.resolve()


def test_invalid_explicit_override_never_silently_falls_back(tmp_path):
    root = tmp_path / "Program Files"
    auto = _installation(root, "5.2")
    selected = blender_locator.find_blender_executable(
        environ={"BLENDER_EXECUTABLE": str(tmp_path / "not_installed.exe"), "PROGRAMFILES": str(root)},
        windows=True, which=lambda _: str(auto),
    )
    assert selected is None


def test_blender_from_path_if_not_in_standard_install_dir(tmp_path):
    executable = tmp_path / "portable" / "blender.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"fake")
    selected = blender_locator.find_blender_executable(
        environ={},
        windows=True,
        which=lambda name: str(executable) if name == "blender.exe" else None,
    )
    assert selected == executable.resolve()


def test_unrecognised_installer_folder_is_ignored(tmp_path):
    root = tmp_path / "Program Files"
    folder = root / "Blender Foundation" / "Blender malicious"
    folder.mkdir(parents=True)
    (folder / "blender.exe").write_bytes(b"fake")
    assert blender_locator.find_blender_executable(
        environ={"PROGRAMFILES": str(root)}, windows=True, which=lambda _: None,
    ) is None


def test_locator_check_verifies_version_without_launching_gui(monkeypatch, tmp_path, capsys):
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"placeholder")
    monkeypatch.setattr(blender_locator, "find_blender_executable", lambda: executable)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="Blender 4.5.0\n", stderr="")

    monkeypatch.setattr(blender_locator.subprocess, "run", fake_run)
    assert blender_locator.main(["--check"]) == 0
    assert calls[0][0] == [str(executable), "--version"]
    assert calls[0][1]["shell"] is False
    assert "Blender 4.5.0" in capsys.readouterr().out


def test_preflight_uses_located_blender_and_remains_offline(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fixture")
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(workspace))
    monkeypatch.delenv("BLENDER_EXECUTABLE", raising=False)
    monkeypatch.setattr(cli, "find_blender_executable", lambda: executable)
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="Blender 4.5.0\n", stderr="",
    ))

    report = cli.preflight()
    assert report["status"] == "ready"
    assert report["blender"]["path"] == str(executable)
    assert report["network_request_performed"] is False
    assert report["render_started"] is False


def test_blender_cli_reads_project_from_environment_without_cmd_interpolation(monkeypatch, tmp_path):
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"fake")
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("LOCAL_AGENT_PROJECT_NAME", "mia_scene_1")
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(workspace))
    monkeypatch.delenv("BLENDER_EXECUTABLE", raising=False)
    monkeypatch.setattr(blender_cli, "find_blender_executable", lambda: executable)
    monkeypatch.setattr(sys, "argv", ["blender_cli"])
    seen = {}

    class FakeBridge:
        def __init__(self, blender, workspace, **kwargs):
            seen["blender"] = str(blender)
            seen["workspace"] = str(workspace)

        def run_task(self, task, **kwargs):
            seen["project"] = kwargs["project_name"]
            return {"status": "completed"}

    monkeypatch.setattr(blender_cli, "BlenderBridge", FakeBridge)
    assert blender_cli.main() == 0
    assert seen["blender"] == str(executable)
    assert seen["workspace"] == str(workspace)
    assert seen["project"] == "mia_scene_1"


@pytest.mark.parametrize("unsafe", ['mia" & echo UNEXPECTED', "../escape", "bad project"])
def test_blender_cli_rejects_unsafe_environment_project_name(monkeypatch, tmp_path, unsafe):
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"placeholder")
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(executable))
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_AGENT_PROJECT_NAME", unsafe)
    monkeypatch.setattr(sys, "argv", ["blender_cli"])
    # Name validation must fail before trying to launch Blender.
    assert blender_cli.main() == 2


def test_windows_batch_launcher_never_interpolates_typed_project_name_in_commands():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "run_blender_agent.bat").read_text(encoding="utf-8")
    setup = (root / "setup_blender_agent.bat").read_text(encoding="utf-8")
    assert 'set /p "LOCAL_AGENT_PROJECT_NAME=' in launcher
    assert " -m local_agent.blender_cli\n" in launcher.replace("\r\n", "\n")
    assert "%PROJECT_NAME%" not in launcher
    assert "%LOCAL_AGENT_PROJECT_NAME%" not in launcher
    assert 'set "BLENDER_EXECUTABLE=C:' not in launcher
    assert 'set "BLENDER_EXECUTABLE=C:' not in setup
    assert "local_agent.blender_locator --check" in setup
