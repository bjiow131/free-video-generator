"""Source-level contracts for the current Images / Video / History interface.

Removed film and production screens are deliberately not required by these
tests: the current application uses separate image/video pages.
Browser integration tests remain an independent release requirement.
"""
from pathlib import Path


HTML = Path(__file__).resolve().parents[1] / "static" / "ai-studio.html"


def test_frontend_has_complete_script_and_current_task_workflows():
    source = HTML.read_text(encoding="utf-8")
    assert "</script></body></html>" in source
    assert "async function generateImage()" in source
    assert "async function generateVideo()" in source
    assert "async function loadHistory()" in source
    assert "async function restoreActiveVideoTask()" in source
    assert "async function openResult(id,type)" in source


def test_frontend_history_escapes_server_task_text_and_avoids_inline_code():
    source = HTML.read_text(encoding="utf-8")
    assert "escapeHtml(x.task_id||'ID отсутствует')" in source
    assert "escapeHtml(statusText)" in source
    assert 'onclick="openResult' not in source
    assert 'data-task-id="'+ "'+escapeHtml(x.task_id)+'" in source
    assert "document.addEventListener('click',event=>" in source


def test_regression_runner_allows_environment_endpoints():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "regression_runner.py").read_text(encoding="utf-8")
    assert 'os.environ.get("REGRESSION_SERVER_URL", "http://localhost:8765")' in source
    assert 'os.environ.get("AGNES_REGRESSION_WORKING_DIR"' in source


def test_images_and_video_have_separate_validated_controls():
    source = HTML.read_text(encoding="utf-8")
    for element_id in (
        "imagePrompt", "imageQuality", "imageAspect", "videoPrompt",
        "videoMode", "videoDuration", "videoAspect", "videoQuality",
    ):
        assert f'id="{element_id}"' in source
    assert "const validAspects=new Set(['9:16','16:9','1:1']);" in source
    assert "if(quality!=='720P')" in source


def test_video_task_survives_refresh_without_replaying_it():
    source = HTML.read_text(encoding="utf-8")
    assert "localStorage.setItem('aistudio_active_video_task',taskId)" in source
    assert "async function restoreActiveVideoTask()" in source
    assert "await restoreActiveVideoTask();" in source
    assert "localStorage.removeItem('aistudio_active_video_task')" in source


def test_image_generation_validates_api_response_and_broken_media():
    source = HTML.read_text(encoding="utf-8")
    assert "if(!r.ok||!d.task_id)throw new Error" in source
    assert "const resultImage=$('#imageResult img');" in source
    assert "resultImage.addEventListener('error'" in source
    assert "$('#saveImageButton').disabled=true" in source


def test_video_generation_checks_provider_errors_and_supports_cancel():
    source = HTML.read_text(encoding="utf-8")
    assert "async function generateVideo()" in source
    assert "if(!r.ok)throw new Error" in source
    assert "if(!taskId)throw new Error" in source
    assert "async function cancelVideoGeneration()" in source
    assert "videoCancelRequested" in source


def test_form_state_is_saved_and_restored_for_both_creation_pages():
    source = HTML.read_text(encoding="utf-8")
    assert "FORM_STATE_KEY" in source
    assert "function saveFormState()" in source
    assert "function restoreFormState()" in source
    assert "function bindFormState()" in source
    assert "restoreFormState();" in source
    assert "bindFormState();" in source


def test_character_refs_and_scene_continuity_are_preserved():
    source = HTML.read_text(encoding="utf-8")
    assert "async function getMiaRefs()" in source
    assert "async function restoreStartFramePreview()" in source
    assert "async function useLastVideoFrame(" in source
    assert "generatedStartFrameTaskId.startsWith('continuity:')" in source


def test_current_history_renderer_has_no_removed_film_workflow():
    source = HTML.read_text(encoding="utf-8")
    assert "function historyCard(x)" in source
    assert "async function legacyLoadHistory" not in source
    assert "async function startFilm" not in source
    assert "async function watchFilm" not in source
