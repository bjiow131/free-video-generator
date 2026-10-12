from __future__ import annotations

import json
import threading
from types import SimpleNamespace

from local_agent import restart_control
from local_agent.studio_server import _renders_idle


def test_restart_request_is_written_only_for_live_studio(monkeypatch, tmp_path):
    project = tmp_path / "mia_story"
    project.mkdir()
    restart_control.write_server_status(project, 1234, 8765)
    monkeypatch.setattr(restart_control, "_studio_is_alive", lambda status: True)

    result = restart_control.request_agent_restart(project, "restart-1", tmp_path / "launch.bat")

    assert result == {
        "status": "completed",
        "action": "studio_restart_scheduled",
        "browser_will_open": True,
        "studio_pid": 1234,
    }
    request = restart_control.peek_restart_request(project)
    assert request["task_id"] == "restart-1"
    restart_control.clear_restart_request(project, "restart-1")
    assert restart_control.peek_restart_request(project) is None


def test_restart_opens_studio_when_no_live_status_exists(monkeypatch, tmp_path):
    project = tmp_path / "mia_story"
    project.mkdir()
    launched = []
    monkeypatch.setattr(restart_control, "_launch_studio", lambda path: launched.append(path))

    result = restart_control.request_agent_restart(project, "restart-2", tmp_path / "run.bat")

    assert result["action"] == "studio_opened"
    assert result["browser_will_open"] is True
    assert launched == [tmp_path / "run.bat"]


def test_malformed_restart_marker_is_discarded(tmp_path):
    project = tmp_path / "mia_story"
    project.mkdir()
    marker = project / ".studio_restart_request.json"
    marker.write_text("[]", encoding="utf-8")

    assert restart_control.peek_restart_request(project) is None
    assert not marker.exists()


def test_restart_waits_for_all_render_paths():
    server = SimpleNamespace(
        jobs=SimpleNamespace(lock=threading.Lock(), active=None),
        render_lock=threading.Lock(),
        render_status={"state": "idle"},
    )
    assert _renders_idle(server)

    server.jobs.active = "scene-job"
    assert not _renders_idle(server)
    server.jobs.active = None
    server.render_status = {"state": "running"}
    assert not _renders_idle(server)
    server.render_status = {"state": "completed"}
    assert _renders_idle(server)
