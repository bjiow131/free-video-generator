"""Guarantee Blender-agent checks never silently fall back to cloud app tests."""
import ast
import sys
from pathlib import Path

import pytest

from local_agent import test_scope


def test_agent_test_scope_contains_only_explicit_local_agent_files():
    selected = test_scope.TEST_SUITES["all"]
    assert selected
    assert len(selected) == len(set(selected))
    assert all(path.startswith("tests/test_") and path.endswith(".py") for path in selected)
    assert all((test_scope.PROJECT_ROOT / path).is_file() for path in selected)
    assert not any(
        fragment in path.lower()
        for path in selected
        for fragment in ("agnes", "server_", "frontend", "pipeline_async_io", "test_core.py")
    )


def test_agent_test_command_has_no_repository_wide_discovery():
    command = test_scope.test_command("all")
    assert command[:4] == [sys.executable, "-m", "pytest", "-q"]
    assert command[4:] == list(test_scope.TEST_SUITES["all"])
    assert "tests" not in command and "." not in command
    assert "--ignore" not in command


def test_agent_suite_rejects_missing_files_instead_of_testing_other_apps(tmp_path):
    with pytest.raises(FileNotFoundError, match="Blender agent test files"):
        test_scope.test_command("security", root=tmp_path)


def test_agent_suite_rejects_unrecognised_test_set():
    with pytest.raises(ValueError, match="Unknown Blender agent"):
        test_scope.test_command("cloud-video")


def test_agent_python_modules_do_not_import_legacy_server_or_cloud_pipelines():
    root = test_scope.PROJECT_ROOT / "local_agent"
    checked = []
    for path in sorted(root.glob("*.py")):
        checked.append(path.name)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        forbidden = [name for name in imports if name.split(".", 1)[0] in {"core", "models", "server"}]
        assert forbidden == [], f"{path.name} imports unrelated cloud/web code: {forbidden}"
    assert "blender_bridge.py" in checked and "poller.py" in checked


def test_local_agent_operational_test_commands_are_scoped_to_agent_only():
    cli = (test_scope.PROJECT_ROOT / "local_agent" / "cli.py").read_text(encoding="utf-8")
    poller = (test_scope.PROJECT_ROOT / "local_agent" / "poller.py").read_text(encoding="utf-8")
    assert 'test_command("all", root=ROOT)' in cli
    assert 'test_command("all", root=worktree)' in poller
    assert "legacy_web_server_checked" in cli
    assert "app_address" not in cli


def test_agent_ci_does_not_run_cloud_api_tests():
    workflow = (test_scope.PROJECT_ROOT / ".github" / "workflows" / "local-agent-tests.yml").read_text(encoding="utf-8")
    assert "runs-on: windows-latest" in workflow
    assert "python -m local_agent.test_scope all" in workflow
    assert "python -m local_agent.test_scope security" in workflow
    assert "python -m compileall -q local_agent" in workflow
    for prohibited in ("server.py", "core/api", "models/", "test_agnes_", "test_core.py"):
        assert prohibited not in workflow


def test_agent_status_is_local_and_never_checks_old_web_api(tmp_path, monkeypatch):
    from local_agent import cli

    workspace = tmp_path / "scenes"
    workspace.mkdir()
    blender = tmp_path / "blender.exe"
    blender.write_bytes(b"fixture")
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(workspace))
    monkeypatch.setenv("BLENDER_EXECUTABLE", str(blender))
    monkeypatch.delenv("LOCAL_AGENT_ENABLE_GITHUB_MAILBOX", raising=False)

    result = cli.status()
    assert result["mode"] == "local_blender_agent"
    assert result["workspace_exists"] is True
    assert result["blender_executable_found"] is True
    assert result["mailbox_opted_in"] is False
    assert result["legacy_web_server_checked"] is False
    assert result["remote_request_performed"] is False
    assert result["blender_render_verified"] is False


def test_agent_cli_test_operation_never_runs_unscoped_pytest(monkeypatch):
    from types import SimpleNamespace
    from local_agent import cli

    captured = []

    def fake_run(args, **kwargs):
        captured.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="isolated tests passed", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: object())
    result = cli.run_tests()

    assert result["status"] == "passed"
    assert len(captured) == 1
    assert captured[0][0] == test_scope.test_command("all", root=cli.ROOT)
    assert "tests" not in captured[0][0]
    assert captured[0][1]["cwd"] == cli.ROOT


def test_powershell_mailbox_setup_matches_actual_runtime_contract():
    scripts = test_scope.PROJECT_ROOT / "scripts" / "windows"
    setup = (scripts / "setup_local_agent.ps1").read_text()
    runner = (scripts / "run_local_agent.ps1").read_text()
    assert '"requirements-github-mailbox.txt"' in setup
    assert "-m local_agent.test_scope all" in setup
    assert "LOCAL_AGENT_ALLOW_REMOTE_APPROVAL" not in setup
    assert '$env:LOCAL_AGENT_ENABLE_GITHUB_MAILBOX = "1"' in runner
    assert "-m local_agent.poller *>>" not in runner


def test_acceptance_and_new_agent_subsystems_are_in_operational_scope():
    selected = set(test_scope.TEST_SUITES["all"])
    assert {
        "tests/test_studio_jobs_cancellation.py", "tests/test_studio_live_blender.py",
        "tests/test_studio_assembly.py", "tests/test_prompt_pipeline.py",
        "tests/test_github_asset_sync.py", "tests/test_trusted_updates.py",
        "tests/test_camera_quality.py", "tests/test_multiscene_timeline.py",
    } <= selected
