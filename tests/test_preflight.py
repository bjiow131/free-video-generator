from __future__ import annotations
from pathlib import Path
from local_agent import cli

def test_preflight_reports_missing_setup_without_network_or_render(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("LOCAL_AGENT_GITHUB_REPO", raising=False)
    monkeypatch.delenv("LOCAL_AGENT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("LOCAL_AGENT_ALLOW_ENV_TOKEN", raising=False)
    monkeypatch.delenv("BLENDER_EXECUTABLE", raising=False)
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)
    monkeypatch.setattr(cli, "_tool_version", lambda _command: {"available": False})
    result = cli.preflight()
    assert result["status"] == "needs_setup"
    assert result["checks"]["workspace_ready"] is True
    assert result["checks"]["mailbox_configured"] is False
    assert result["checks"]["blender_available"] is False
    assert result["network_request_performed"] is False
    assert result["render_started"] is False
    assert result["secret_values_returned"] is False

def test_preflight_handles_unconfigured_workspace(monkeypatch):
    monkeypatch.delenv("LOCAL_AGENT_WORKSPACE", raising=False)
    monkeypatch.delenv("LOCAL_AGENT_GITHUB_REPO", raising=False)
    monkeypatch.delenv("LOCAL_AGENT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("LOCAL_AGENT_ALLOW_ENV_TOKEN", raising=False)
    monkeypatch.delenv("BLENDER_EXECUTABLE", raising=False)
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)
    monkeypatch.setattr(cli, "_tool_version", lambda _command: {"available": False})
    result = cli.preflight()
    assert result["checks"]["workspace_ready"] is False
    assert result["workspace"]["configured"] is False
