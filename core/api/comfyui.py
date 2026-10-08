"""Optional local ComfyUI API integration."""
from core.timing import timed_step

from __future__ import annotations
import asyncio
import copy
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode
import requests

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKFLOW_PATH = PROJECT_ROOT / "workflows" / "comfyui" / "workflow.json"
DEFAULT_BASE_URL = "http://127.0.0.1:8188"

class ComfyUIError(RuntimeError):
    """Raised when ComfyUI cannot accept or finish a workflow."""

def get_comfyui_base_url() -> str:
    return os.environ.get("COMFYUI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")

def get_comfyui_workflow_path() -> Path:
    return Path(os.environ.get("COMFYUI_WORKFLOW_PATH", str(DEFAULT_WORKFLOW_PATH)))

def _load_workflow(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ComfyUIError(f"ComfyUI workflow not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            workflow = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ComfyUIError(f"Invalid ComfyUI workflow: {path}") from exc
    if not isinstance(workflow, dict) or not workflow:
        raise ComfyUIError("ComfyUI workflow must be a non-empty API-format object")
    return workflow

def _set_node_input(workflow: dict[str, Any], node_id: str, input_name: str, value: Any) -> None:
    node = workflow.get(str(node_id))
    if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
        raise ComfyUIError(f"ComfyUI node {node_id!r} does not contain inputs")
    node["inputs"][input_name] = value

def build_workflow(*, prompt: Optional[str] = None, seed: Optional[int] = None,
                   width: Optional[int] = None, height: Optional[int] = None,
                   workflow_path: Optional[Path] = None) -> dict[str, Any]:
    workflow = copy.deepcopy(_load_workflow(workflow_path or get_comfyui_workflow_path()))
    bindings = (
        ("COMFYUI_PROMPT_NODE", "COMFYUI_PROMPT_INPUT", prompt),
        ("COMFYUI_SEED_NODE", "COMFYUI_SEED_INPUT", seed),
        ("COMFYUI_WIDTH_NODE", "COMFYUI_WIDTH_INPUT", width),
        ("COMFYUI_HEIGHT_NODE", "COMFYUI_HEIGHT_INPUT", height),
    )
    for node_env, input_env, value in bindings:
        node_id = os.environ.get(node_env, "").strip()
        input_name = os.environ.get(input_env, "").strip()
        if value is None or not node_id:
            continue
        if not input_name:
            raise ComfyUIError(f"{input_env} must be set when {node_env} is configured")
        _set_node_input(workflow, node_id, input_name, value)
    return workflow

class ComfyUIClient:
    """Async wrapper around ComfyUI's local HTTP API."""

    def __init__(self, base_url: Optional[str] = None, client_id: Optional[str] = None):
        self.base_url = (base_url or get_comfyui_base_url()).rstrip("/")
        self.client_id = client_id or os.environ.get("COMFYUI_CLIENT_ID", "free-video-generator")

    async def health(self) -> dict[str, Any]:
        def _request() -> requests.Response:
            return requests.get(f"{self.base_url}/system_stats", timeout=(3, 5))
        try:
            response = await asyncio.to_thread(_request)
            response.raise_for_status()
            return {"available": True, "base_url": self.base_url, "system": response.json()}
        except (requests.RequestException, ValueError) as exc:
            return {"available": False, "base_url": self.base_url, "error": str(exc)}

    async def queue_prompt(self, workflow: dict[str, Any]) -> str:
        payload = {"prompt": workflow, "client_id": self.client_id}
        def _request() -> requests.Response:
            return requests.post(f"{self.base_url}/prompt", json=payload, timeout=(5, 15))
        try:
            response = await asyncio.to_thread(_request)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ComfyUIError(f"ComfyUI queue request failed: {exc}") from exc
        if data.get("error"):
            raise ComfyUIError(f"ComfyUI rejected workflow: {data['error']}")
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError("ComfyUI did not return prompt_id")
        return str(prompt_id)

    async def wait_for_history(self, prompt_id: str, timeout: float = 1800.0,
                               poll_interval: float = 1.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            def _request() -> requests.Response:
                return requests.get(f"{self.base_url}/history/{prompt_id}", timeout=(5, 15))
            try:
                response = await asyncio.to_thread(_request)
                response.raise_for_status()
                data = response.json()
            except (requests.RequestException, ValueError) as exc:
                logger.warning("ComfyUI history poll failed: %s", exc)
                await asyncio.sleep(poll_interval)
                continue
            if prompt_id in data:
                result = data[prompt_id]
                status = result.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyUIError(f"ComfyUI workflow failed: {status}")
                return result
            await asyncio.sleep(poll_interval)
        raise ComfyUIError(f"ComfyUI workflow timed out after {timeout:.0f}s")


    def extract_outputs(self, history: dict[str, Any]) -> list[dict[str, str]]:
        """Return downloadable ComfyUI output descriptors from a completed history."""
        outputs: list[dict[str, str]] = []
        for node_output in (history.get("outputs") or {}).values():
            if not isinstance(node_output, dict):
                continue
            for kind in ("images", "gifs", "videos", "audio"):
                items = node_output.get(kind) or []
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict) or not item.get("filename"):
                        continue
                    descriptor = {
                        "filename": str(item["filename"]),
                        "subfolder": str(item.get("subfolder") or ""),
                        "type": str(item.get("type") or "output"),
                        "kind": kind,
                    }
                    descriptor["url"] = (
                        f"{self.base_url}/view?"
                        + urlencode({
                            "filename": descriptor["filename"],
                            "subfolder": descriptor["subfolder"],
                            "type": descriptor["type"],
                        })
                    )
                    outputs.append(descriptor)
        return outputs

    async def download_output(self, output: dict[str, str], destination: Path) -> Path:
        """Download a ComfyUI /view output atomically."""
        params = {
            "filename": output["filename"],
            "subfolder": output.get("subfolder", ""),
            "type": output.get("type", "output"),
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")

        def _request() -> requests.Response:
            return requests.get(f"{self.base_url}/view", params=params, timeout=(5, 60))

        try:
            response = await asyncio.to_thread(_request)
            response.raise_for_status()
            await asyncio.to_thread(temporary.write_bytes, response.content)
            await asyncio.to_thread(temporary.replace, destination)
            return destination
        except (requests.RequestException, OSError) as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ComfyUIError(f"ComfyUI output download failed: {exc}") from exc

    async def generate(self, *, prompt: Optional[str] = None, seed: Optional[int] = None,
                       width: Optional[int] = None, height: Optional[int] = None,
                       workflow_path: Optional[Path] = None, timeout: float = 1800.0) -> dict[str, Any]:
        workflow = build_workflow(prompt=prompt, seed=seed, width=width, height=height,
                                  workflow_path=workflow_path)
        prompt_id = await self.queue_prompt(workflow)
        history = await self.wait_for_history(prompt_id, timeout=timeout)
        return {"prompt_id": prompt_id, "history": history, "outputs": self.extract_outputs(history)}

async def check_comfyui() -> dict[str, Any]:
    return await ComfyUIClient().health()
