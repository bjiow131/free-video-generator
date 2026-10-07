import json
import pytest
from core.api.comfyui import ComfyUIError, build_workflow

def test_build_workflow_loads_api_format_and_applies_bindings(tmp_path, monkeypatch):
    workflow = {"3": {"class_type": "KSampler", "inputs": {"seed": 1}},
                "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}}}
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    monkeypatch.setenv("COMFYUI_PROMPT_NODE", "6")
    monkeypatch.setenv("COMFYUI_PROMPT_INPUT", "text")
    monkeypatch.setenv("COMFYUI_SEED_NODE", "3")
    monkeypatch.setenv("COMFYUI_SEED_INPUT", "seed")
    result = build_workflow(prompt="new prompt", seed=123, workflow_path=path)
    assert result["6"]["inputs"]["text"] == "new prompt"
    assert result["3"]["inputs"]["seed"] == 123

def test_build_workflow_rejects_missing_file(tmp_path):
    with pytest.raises(ComfyUIError):
        build_workflow(workflow_path=tmp_path / "missing.json")

def test_build_workflow_rejects_empty_workflow(tmp_path):
    path = tmp_path / "workflow.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ComfyUIError):
        build_workflow(workflow_path=path)

def test_build_workflow_does_not_mutate_source(tmp_path, monkeypatch):
    workflow = {"1": {"class_type": "Node", "inputs": {"value": "old"}}}
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    monkeypatch.setenv("COMFYUI_PROMPT_NODE", "1")
    monkeypatch.setenv("COMFYUI_PROMPT_INPUT", "value")
    result = build_workflow(prompt="new", workflow_path=path)
    assert result["1"]["inputs"]["value"] == "new"
    assert json.loads(path.read_text(encoding="utf-8")) == workflow


def test_extract_outputs_builds_view_urls():
    from core.api.comfyui import ComfyUIClient

    client = ComfyUIClient(base_url="http://127.0.0.1:8188")
    result = client.extract_outputs({
        "outputs": {
            "9": {
                "images": [
                    {"filename": "sample.png", "subfolder": "free-video", "type": "output"}
                ]
            }
        }
    })
    assert result[0]["filename"] == "sample.png"
    assert result[0]["kind"] == "images"
    assert result[0]["url"].startswith("http://127.0.0.1:8188/view?")


def test_extract_outputs_ignores_malformed_items():
    from core.api.comfyui import ComfyUIClient

    client = ComfyUIClient(base_url="http://127.0.0.1:8188")
    result = client.extract_outputs({
        "outputs": {
            "9": {
                "images": [None, {}, {"subfolder": "x"}, {"filename": "ok.png"}],
                "videos": [{"filename": "clip.mp4", "type": "output"}],
            }
        }
    })
    assert [item["filename"] for item in result] == ["ok.png", "clip.mp4"]
