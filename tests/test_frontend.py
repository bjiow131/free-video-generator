from pathlib import Path


HTML = Path(__file__).resolve().parents[1] / "static" / "ai-studio.html"


def test_frontend_has_complete_script_and_task_workflows():
    source = HTML.read_text(encoding="utf-8")
    assert "</script></body></html>" in source
    assert "async function pollTask" in source
    assert "async function startFilm" in source
    assert "async function watchFilm" in source
    assert "if(!r.ok){let d=await r.json().catch(()=>({}));throw Error(d.detail||'Не удалось получить статус фильма')}" in source


def test_frontend_history_escapes_server_task_text():
    source = HTML.read_text(encoding="utf-8")
    assert "escapeHtml(x.task_id)" in source
    assert "escapeHtml(x.status)" in source
    assert 'onclick="openResult' not in source


def test_regression_runner_allows_environment_endpoints():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "regression_runner.py").read_text(encoding="utf-8")
    assert 'os.environ.get("REGRESSION_SERVER_URL", "http://localhost:8765")' in source
    assert 'os.environ.get("AGNES_REGRESSION_WORKING_DIR"' in source
