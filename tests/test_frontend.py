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


def test_simple_generation_has_mode_specific_controls_and_dock_sync():
    source = HTML.read_text(encoding="utf-8")
    assert "function syncCreateDock()" in source
    assert "durationChip.hidden=type!=='video'" in source
    assert "if(type==='image')" in source
    assert 'id="videoDuration"' in source
    assert 'data-create-type="image"' in source
    assert 'data-create-type="video"' in source


def test_production_workflows_persist_and_resume_after_reload():
    source = HTML.read_text(encoding="utf-8")
    assert "localStorage.setItem('production_task_id',d.task_id)" in source
    assert "localStorage.setItem('production_task_kind',kind)" in source
    assert "async function restoreProductionAfterLoad()" in source
    assert "restoreProductionAfterLoad()" in source


def test_frontend_handles_generation_api_failures_and_broken_image_results():
    source = HTML.read_text(encoding="utf-8")
    assert "if(!r.ok||!d.task_id)throw Error(d.detail||d.error||'Не удалось запустить генерацию изображения')" in source
    assert "if(!r.ok||!d.task_id)throw Error(d.detail||d.error||'Не удалось запустить генерацию видео')" in source
    assert "data-retry-generation" in source
    assert "imageResult.addEventListener('error'" in source


def test_frontend_debounces_draft_persistence():
    source = HTML.read_text(encoding="utf-8")
    assert "const draftSaveTimers={}" in source
    assert "function scheduleDraftSave(key,fn,delay=250)" in source
    assert "scheduleDraftSave('simple',saveSimpleDraft)" in source
    assert "scheduleDraftSave('film',saveFilmDraft)" in source
    assert "scheduleDraftSave('production',()=>saveProductionDraft(productionMode))" in source


def test_frontend_does_not_keep_superseded_legacy_history_renderer():
    source = HTML.read_text(encoding="utf-8")
    assert "async function legacyLoadHistory" not in source
    assert "async function openResult(id,type){try{let base=type==='image'" not in source
