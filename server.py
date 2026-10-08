"""
Agnes Video Generator v2.0 — FastAPI 服务层

三种任务类型的路由集成：
- POST /api/tasks/simple      — 简单视频生成
- POST /api/tasks/creative    — 创意长视频生成
- POST /api/tasks/manuscript  — 稿件长视频生成
- POST /api/tasks             — 向后兼容（映射到 creative）

所有类型共享 WebSocket 进度推送、任务列表、任务详情、视频下载等端点。
resume 端点根据 task_type 自动选择对应的 Pipeline。
"""

import asyncio
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import urlsplit
from typing import Dict, List, Optional, Union

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_api_key, set_api_key, delete_api_key, get_api_key_source, get_working_dir, AVAILABLE_VOICES, DURATION_FRAME_MAP, SUPPORTED_AGNES_VIDEO_DURATIONS, get_workspaces, add_workspace, remove_workspace, set_active_workspace, get_active_workspace, REGRESSION_WORKING_DIR_ENV, get_watermark_config, set_watermark_config, WATERMARK_PROMO_TEXT_ZH, WATERMARK_PROMO_TEXT_EN
from core.pipelines import (
    AnchorPipeline,
    BasePipeline,
    PipelineShutdown,
    SimpleVideoPipeline,
    CreativeVideoPipeline,
    ManuscriptVideoPipeline,
)
from core.api.agnes_image import AgnesImageAPI
from core.api.agnes_chat import AgnesChatAPI
from core.api.comfyui import ComfyUIClient, ComfyUIError, build_workflow
from core.task_manager import TaskManager

from models.task import (
    AnchorVideoTask,
    AudioConfig,
    BaseTaskState,
    CreativeVideoTask,
    ManuscriptVideoTask,
    SimpleImageTask,
    SimpleVideoTask,
    StepStatus,
    SubtitleConfig,
    SubtitleStyle,
    TaskType,
    VideoMode,
)


# ═══════════════════════════════════════════════════
# 并发控制（复用回归流程的加权信号量逻辑）
# ═══════════════════════════════════════════════════

# Agnes API 每分钟调用上限（与 rate_limiter.py / regression_runner.py 一致）
_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", "20"))
# 各任务类型权重 = 该类型预估的每分钟 Agnes API 调用数
# 留 50% 余量 => 总权重上限 = _AGNES_RATE_LIMIT / 2
TASK_TYPE_WEIGHTS = {
    TaskType.SIMPLE: 1,       # 1 submit + 轻量轮询
    TaskType.CREATIVE: 3,     # Chat + N*Image + N*Video + 轮询
    TaskType.MANUSCRIPT: 3,   # Chat + images + video polling; one heavy pipeline at a time
    TaskType.ANCHOR: 2,       # 1 i2v submit + 轻量轮询
    TaskType.IMAGE: 1,        # 1 image submit
}
MAX_CONCURRENT_WEIGHT = int(os.environ.get("AGNES_MAX_CONCURRENT_WEIGHT", "3"))


SUPPORTED_VIDEO_DIMENSIONS = {(768, 1152), (1152, 648), (1024, 1024)}

def _validate_video_dimensions(width: int, height: int) -> None:
    """Reject unsupported resolutions before they reach FFmpeg/Agnes."""
    if (width, height) not in SUPPORTED_VIDEO_DIMENSIONS:
        raise HTTPException(status_code=422, detail="Поддерживаются только 9:16, 16:9 и 1:1")


class WeightedSemaphore:
    """加权信号量：控制并发任务的总权重不超过上限。

    每个任务类型的权重 = 该类型预估的每分钟 Agnes API 调用数。
    控制并发任务数，确保总 API 调用 ≤ AGNES_RATE_LIMIT/分钟。
    逻辑与 regression_runner.py 的 WeightedSemaphore 完全一致。
    """
    def __init__(self, max_weight: int):
        self.max_weight = max_weight
        self.current = 0
        self._lock = asyncio.Lock()
        self._cond = asyncio.Condition(self._lock)

    async def acquire(self, weight: int):
        if weight > self.max_weight:
            raise ValueError(f"task weight {weight} > max {self.max_weight}")
        async with self._lock:
            while self.current + weight > self.max_weight:
                await self._cond.wait()
            self.current += weight

    async def release(self, weight: int):
        async with self._lock:
            self.current -= weight
            self._cond.notify_all()

    @property
    def utilization(self) -> float:
        return self.current / self.max_weight if self.max_weight else 0


# 全局加权信号量（服务端所有任务共享）
_pipeline_semaphore = WeightedSemaphore(MAX_CONCURRENT_WEIGHT)
# 排队中的任务: task_id -> weight
_queued_tasks: Dict[str, int] = {}


def _parse_bg_color(raw: str) -> tuple:
    """Parse a subtitle background color as RGB/RGBA or named@alpha."""
    if raw is None:
        return (0, 0, 0, 128)
    if isinstance(raw, tuple):
        if len(raw) not in (3, 4):
            raise ValueError("Цвет должен содержать 3 или 4 компонента")
        return tuple(int(max(0, min(255, value))) for value in raw)
    if not isinstance(raw, str):
        raise ValueError("Цвет должен быть строкой")
    raw = raw.strip()
    if raw.lower() in ("none", "transparent", ""):
        return None
    if raw.startswith("(") and raw.endswith(")"):
        try:
            values = [int(x.strip()) for x in raw[1:-1].split(",")]
        except ValueError as exc:
            raise ValueError("Недопустимый цветовой формат") from exc
        if len(values) not in (3, 4) or any(value < 0 or value > 255 for value in values):
            raise ValueError("RGB/RGBA компоненты должны быть от 0 до 255")
        return tuple(values)
    if "@" in raw:
        color_name, alpha_raw = raw.split("@", 1)
        rgb = {"black": (0, 0, 0), "white": (255, 255, 255),
               "red": (255, 0, 0), "blue": (0, 0, 255),
               "yellow": (255, 255, 0)}.get(color_name.strip().lower())
        if rgb is None:
            raise ValueError("Неподдерживаемый цвет фона")
        try:
            alpha = float(alpha_raw.strip())
        except ValueError as exc:
            raise ValueError("Прозрачность должна быть числом от 0 до 1 или от 0 до 100") from exc
        if 0 <= alpha <= 1:
            alpha_value = round(alpha * 255)
        elif 0 <= alpha <= 100:
            alpha_value = round(alpha / 100 * 255)
        else:
            raise ValueError("Прозрачность должна быть числом от 0 до 1 или от 0 до 100")
        return (*rgb, alpha_value)
    raise ValueError("Недопустимый формат цвета фона")

def _build_position(subtitle_position: str) -> tuple:
    """将 'bottom'/'top' 转为 moviepy 兼容的位置元组。"""
    if subtitle_position == "top":
        return ("center", "top")
    return ("center", "bottom")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


# Suppress noisy WebSocket heartbeat / protocol logs from uvicorn and websockets
logging.getLogger("uvicorn.protocols.websockets").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)

active_connections: Dict[str, WebSocket] = {}
active_pipelines: Dict[str, BasePipeline] = {}
# task_id -> asyncio.Lock, 串行化 create/resume/stop，避免并发操作同一任务导致
# 旧 pipeline 的 finally 误删新 pipeline、或同任务双重运行。
_pipeline_locks: Dict[str, asyncio.Lock] = {}
_task_dir_cache: Dict[str, str] = {}
background_tasks: set = set()
shutdown_event = asyncio.Event()


def _get_pipeline_lock(task_id: str) -> asyncio.Lock:
    """Get the task-level lock, creating it when necessary."""
    lock = _pipeline_locks.get(task_id)
    if lock is None:
        lock = asyncio.Lock()
        _pipeline_locks[task_id] = lock
    return lock


def _rebuild_task_dir_cache() -> None:
    """Rebuild task_id -> dir_name cache for the active workspace."""
    _task_dir_cache.clear()
    working_dir = get_working_dir()
    if not os.path.isdir(working_dir):
        return
    for name in os.listdir(working_dir):
        task_file = os.path.join(working_dir, name, "task_state.json")
        if not os.path.isfile(task_file):
            continue
        try:
            with open(task_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            task_id = data.get("task_id")
            if task_id:
                try:
                    _task_dir_cache[_validate_task_id(task_id)] = _validate_task_id(name)
                except HTTPException:
                    logger.warning("[Security] Ignoring unsafe task cache entry: %s", name)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("[Startup] Failed to index task %s: %s", name, e, exc_info=True)


def _cache_task_dir(task_id: str, dir_name: str) -> None:
    _task_dir_cache[_validate_task_id(task_id)] = _validate_task_id(dir_name)


def _invalidate_task_dir(task_id: str) -> None:
    _task_dir_cache.pop(task_id, None)
def _validate_task_id(task_id: str) -> str:
    """Validate a task identifier before it can influence a filesystem path."""
    if not task_id or len(task_id) > 128 or os.path.basename(task_id) != task_id:
        raise HTTPException(status_code=400, detail="Недопустимый идентификатор задачи")
    if "/" in task_id or chr(92) in task_id or ".." in task_id:
        raise HTTPException(status_code=400, detail="Недопустимый идентификатор задачи")
    return task_id

def _find_dir_name(task_id: str) -> str:
    """Find a task directory using the in-memory cache."""
    task_id = _validate_task_id(task_id)
    return _task_dir_cache.get(task_id, task_id)



# ═══════════════════════════════════════════════════
# Lifespan
# ═══════════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(get_working_dir(), exist_ok=True)
    upload_dir = os.path.join(get_working_dir(), "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    working_dir = get_working_dir()
    if os.path.exists(working_dir):
        for name in os.listdir(working_dir):
            task_file = os.path.join(working_dir, name, "task_state.json")
            if os.path.exists(task_file):
                try:
                    with open(task_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("status") in ("running", "queued"):
                        old_status = data["status"]
                        data["status"] = "pending"
                        # H5: 原子写（临时文件 + os.replace），避免写入中途崩溃损坏 JSON
                        tmp_fd, tmp_path = tempfile.mkstemp(
                            dir=os.path.join(working_dir, name), suffix=".tmp"
                        )
                        try:
                            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                                json.dump(data, f, ensure_ascii=False, indent=2)
                            os.replace(tmp_path, task_file)
                        except Exception:
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                            raise
                        logger.info(f"[Startup] Reset stale {old_status} task {name} -> pending")
                except Exception as e:
                    logger.warning(f"[Startup] Failed to reset stale task {name}: {e}", exc_info=True)

    _rebuild_task_dir_cache()

    yield


app = FastAPI(title="AI Studio API", lifespan=lifespan)

# Local-only browser UI: allow only the two loopback origins used by the
# built-in server.  The UI itself is same-origin, but keeping explicit CORS
# support is useful for localhost development without exposing the API to
# arbitrary websites.
_LOCAL_CORS_ORIGINS = [
    "http://127.0.0.1:8765",
    "http://localhost:8765",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_LOCAL_CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

_LOCAL_SERVER_PORT = int(os.environ.get("PORT", "8765"))
_LOCAL_ALLOWED_HOSTS = {
    f"127.0.0.1:{_LOCAL_SERVER_PORT}",
    f"localhost:{_LOCAL_SERVER_PORT}",
}
for _configured_host in (
    os.environ.get("ALLOWED_HOST", ""),
    os.environ.get("PUBLIC_HOST", ""),
    os.environ.get("RENDER_EXTERNAL_HOSTNAME", ""),
):
    if _configured_host:
        _LOCAL_ALLOWED_HOSTS.add(_configured_host.lower().removeprefix("https://").removeprefix("http://").rstrip("/"))

def _origin_matches_host(origin: str, host: str) -> bool:
    """Require a supplied Origin to be same-origin with the validated Host."""
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == host
    except ValueError:
        return False

def _request_host_allowed(host: str) -> bool:
    return host in _LOCAL_ALLOWED_HOSTS

@app.middleware("http")
async def local_origin_guard(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        host = request.headers.get("host", "").lower()
        if not _request_host_allowed(host):
            return JSONResponse(status_code=403, content={"detail": "Недопустимый адрес сервера"})
        if not _origin_matches_host(origin, host):
            return JSONResponse(status_code=403, content={"detail": "Недопустимый источник запроса"})
    return await call_next(request)

def get_upload_dir() -> str:
    """返回当前激活工作目录下的 uploads 子目录。"""
    return os.path.join(get_working_dir(), "uploads")

MAX_UPLOAD_SIZE = 10 * 1024 * 1024
_ALLOWED_IMAGE_SIGNATURES = {
    ".png": lambda head: head.startswith(b"\x89PNG\r\n\x1a\n"),
    ".jpg": lambda head: head.startswith(b"\xff\xd8\xff"),
    ".webp": lambda head: head.startswith(b"RIFF") and head[8:12] == b"WEBP",
}

async def _save_image_upload(upload: UploadFile, stem: str) -> str:
    """Validate and persist a reference image with a 10 MB limit."""
    if not upload or not upload.filename:
        return ""
    await upload.seek(0)
    data = bytearray()
    while len(data) <= MAX_UPLOAD_SIZE:
        chunk = await upload.read(min(1024 * 1024, MAX_UPLOAD_SIZE + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Размер изображения не должен превышать 10 МБ")
    header = bytes(data[:16])
    extension = next((ext for ext, check in _ALLOWED_IMAGE_SIGNATURES.items() if check(header)), None)
    if extension is None:
        raise HTTPException(status_code=422, detail="Поддерживаются только изображения PNG, JPG/JPEG и WEBP")
    allowed_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".webp": "image/webp",
    }
    content_type = (upload.content_type or "").lower().split(";", 1)[0].strip()
    if content_type and content_type != allowed_types[extension]:
        raise HTTPException(status_code=422, detail="Тип изображения не соответствует содержимому файла")
    upload_dir = get_upload_dir()
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, f"{stem}{extension}")
    try:
        await asyncio.to_thread(_write_upload_bytes, path, bytes(data))
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    return path

def _write_upload_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)

def _validate_workspace_path(raw_path: str) -> str:
    """Validate a workspace path before it is persisted or created."""
    path = (raw_path or "").strip()
    if not path:
        raise HTTPException(status_code=422, detail="Путь рабочей папки не может быть пустым")
    normalized = path.replace("\\", "/")
    if any(part == ".." for part in normalized.split("/")):
        raise HTTPException(status_code=422, detail="Путь рабочей папки не должен содержать ..")
    candidate = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    if not os.path.isabs(candidate):
        raise HTTPException(status_code=422, detail="Путь рабочей папки должен быть абсолютным")
    if os.path.exists(candidate) and not os.path.isdir(candidate):
        raise HTTPException(status_code=422, detail="Путь рабочей папки должен указывать на каталог")
    parent = os.path.dirname(candidate)
    if not os.path.isdir(parent):
        raise HTTPException(status_code=422, detail="Родительская папка рабочей директории не существует")
    protected = []
    if platform.system() == "Windows":
        for env_name in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "ProgramW6432", "CommonProgramFiles"):
            value = os.environ.get(env_name)
            if value:
                protected.append(os.path.realpath(os.path.abspath(value)))
    else:
        protected.extend(os.path.realpath(p) for p in (
            "/etc", "/usr", "/bin", "/sbin", "/var", "/proc", "/sys", "/dev", "/boot", "/lib", "/lib64", "/run"
        ))
    protected.append(os.path.realpath(_PROJECT_ROOT))
    for protected_dir in protected:
        try:
            if os.path.commonpath([candidate, protected_dir]) == protected_dir:
                if os.path.realpath(candidate) != os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".working_dir")):
                    raise HTTPException(status_code=422, detail="Нельзя использовать системную или служебную папку как рабочую")
        except ValueError:
            continue
    if os.path.realpath(candidate) == os.path.realpath(os.path.dirname(candidate)):
        raise HTTPException(status_code=422, detail="Недопустимая рабочая папка")
    return candidate


# ═══════════════════════════════════════════════════
# WebSocket
# ═══════════════════════════════════════════════════


@app.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    try:
        _validate_task_id(task_id)
    except HTTPException:
        await websocket.close(code=1008, reason="Недопустимый идентификатор задачи")
        return
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host", "").lower()
    if not _request_host_allowed(host):
        await websocket.close(code=1008, reason="Недопустимый адрес сервера")
        return
    if not _origin_matches_host(origin, host):
        await websocket.close(code=1008, reason="Недопустимый источник запроса")
        return
    await websocket.accept()
    logger.info(f"[WS] Client connected for task {task_id}")

    # 关闭并替换同一 task_id 的旧 WS 连接，避免覆盖竞态
    old_ws = active_connections.get(task_id)
    if old_ws is not None and old_ws is not websocket:
        logger.info(f"[WS] Closing previous connection for task {task_id}")
        try:
            await old_ws.close(code=1000, reason="replaced by new connection")
        except Exception as e:
            logger.debug(f"[WS] Error closing old WS for {task_id}: {e}")
    active_connections[task_id] = websocket

    if task_id in active_pipelines:
        logger.info(f"[WS] Binding existing pipeline for task {task_id}")
        active_pipelines[task_id].progress_callback = _make_progress_callback(task_id)

    try:
        while True:
            msg = await websocket.receive_text()
            if not msg or msg.strip().lower() in ("ping", "pong"):
                continue
    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected for task {task_id}")
    except Exception as e:
        logger.warning(f"[WS] Error for task {task_id}: {e}")
    finally:
        # 仅当当前 WS 仍是活跃连接时才删除，避免误删已替换的新连接
        if active_connections.get(task_id) is websocket:
            del active_connections[task_id]


# ═══════════════════════════════════════════════════
# Static files + Root
# ═══════════════════════════════════════════════════


@app.get("/health")
async def health():
    ffmpeg_path = shutil.which("ffmpeg")
    ffmpeg_version = ""
    if ffmpeg_path:
        try:
            result = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True, timeout=5, check=False)
            first_line = (result.stdout or result.stderr).splitlines()
            if first_line:
                match = re.search(r"ffmpeg version\s+([^\s]+)", first_line[0])
                ffmpeg_version = match.group(1) if match else first_line[0]
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.warning("[Health] FFmpeg version check failed: %s", e, exc_info=True)
    return {
        "ok": True,
        "service": "AI Studio API",
        "ffmpeg": bool(ffmpeg_path),
        "ffmpeg_version": ffmpeg_version,
        "api_key_configured": bool(get_api_key()),
    }


static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    studio_path = os.path.join(os.path.dirname(__file__), "static", "ai-studio.html")
    if os.path.exists(studio_path):
        return FileResponse(studio_path)
    return {"message": "AI Studio API"}


# ═══════════════════════════════════════════════════
# API Key 配置
# ═══════════════════════════════════════════════════


@app.get("/api/config")
async def get_config(request: Request):
    key = get_api_key()
    source = get_api_key_source()
    active_ws = get_active_workspace()
    wm = get_watermark_config()
    data = {
        "configured": bool(key),
        "source": source,
        "can_clear": source == "config",
        "workspaces": get_workspaces(),
        "active_workspace": active_ws,
        "working_dir_source": "regression" if os.environ.get(REGRESSION_WORKING_DIR_ENV) else "config",
        "watermark": wm,
        "watermark_promo_zh": WATERMARK_PROMO_TEXT_ZH,
        "watermark_promo_en": WATERMARK_PROMO_TEXT_EN,
    }
    return data


@app.post("/api/config")
async def save_config(api_key: str = Form(...), request: Request = None):
    api_key = api_key.strip()
    if not api_key:
        raise HTTPException(status_code=422, detail="API Key не может быть пустым")
    set_api_key(api_key)
    return {"ok": True, "configured": True}


@app.delete("/api/config")
async def clear_config(request: Request):
    """Delete the API key from the config file."""
    source = get_api_key_source()
    if source == "env":
        raise HTTPException(
            status_code=400,
            detail="API Key 来自环境变量，无法从界面清除",
        )
    delete_api_key()
    return {"ok": True}


# ═══════════════════════════════════════════════════
# 水印配置
# ═══════════════════════════════════════════════════


@app.post("/api/config/watermark")
async def save_watermark_config(enabled: bool = Form(False), request: Request = None):
    """Save watermark toggle."""
    set_watermark_config(enabled=enabled)
    return {"ok": True, "enabled": enabled}


# ═══════════════════════════════════════════════════
# 创意词设计（Agnes Chat API）
# ═══════════════════════════════════════════════════


@app.post("/api/ideas/generate")
async def generate_ideas(keyword: str = Form(...), request: Request = None):
    """使用 Agnes LLM 根据关键词生成创意概念和视觉风格建议。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="Сначала настройте ключ API")
    client = AgnesChatAPI(api_key)
    system_prompt = (
        "你是一个专业的视频创意策划师。用户会给你一个关键词，请你输出一个 JSON 对象，"
        "包含两个字段：concept（创意概念描述，一段 80-150 字的中文描述）和 style（视觉风格描述，一段 60-120 字的中文描述）。"
        "只用 JSON 格式回复，不要有其他文字。"
    )
    user_prompt = f"请根据关键词「{keyword}」生成创意概念和视觉风格建议。"
    try:
        result = client.chat_json(system_prompt, user_prompt, max_tokens=2048)
    except Exception:
        logger.exception("[Ideas] Generation failed")
        raise HTTPException(status_code=502, detail="Не удалось сгенерировать идеи. Проверьте API и повторите попытку.")
    return {
        "ok": True,
        "concept": result.get("concept", ""),
        "style": result.get("style", ""),
    }


# ═══════════════════════════════════════════════════
# 工作目录管理（多工作目录，同时仅一个 active）
# ═══════════════════════════════════════════════════


@app.get("/api/workspaces")
async def list_workspaces(request: Request):
    """列出所有已配置的工作目录及当前激活项。"""
    return {
        "workspaces": get_workspaces(),
        "active_workspace": get_active_workspace(),
    }


@app.post("/api/workspaces")
async def create_workspace(path: str = Form(...), name: str = Form(""), request: Request = None):
    """添加一个工作目录。"""
    safe_path = _validate_workspace_path(path)
    entry = add_workspace(safe_path, name.strip())
    os.makedirs(entry["path"], exist_ok=True)
    os.makedirs(os.path.join(entry["path"], "uploads"), exist_ok=True)
    return {"ok": True, "workspace": entry, "active_workspace": get_active_workspace()}


@app.delete("/api/workspaces")
async def delete_workspace(path: str = Form(...), request: Request = None):
    """移除一个工作目录（仅从配置中移除，不删除磁盘文件）。"""
    safe_path = _validate_workspace_path(path)
    removed = remove_workspace(safe_path)
    if not removed:
        raise HTTPException(status_code=404, detail="Рабочая папка не найдена")
    return {"ok": True, "active_workspace": get_active_workspace()}


@app.post("/api/workspaces/active")
async def activate_workspace(path: str = Form(...), request: Request = None):
    """设置当前激活的工作目录。"""
    safe_path = _validate_workspace_path(path)
    try:
        active = set_active_workspace(safe_path)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    os.makedirs(active, exist_ok=True)
    os.makedirs(os.path.join(active, "uploads"), exist_ok=True)
    _rebuild_task_dir_cache()
    return {"ok": True, "active_workspace": active}


@app.post("/api/workspaces/pick-directory")
async def pick_directory(request: Request):
    """弹出操作系统原生目录选择框，返回所选目录路径。

    跨平台实现：
    - macOS: osascript
    - Linux: zenity（若不可用回退 kdialog）
    - Windows: PowerShell Forms.FolderBrowserDialog
    """
    path = await asyncio.to_thread(_pick_directory_native)
    if not path:
        return {"ok": False, "path": ""}
    return {"ok": True, "path": path}


def _pick_directory_native() -> str:
    """同步调用系统原生目录选择器，返回路径或空字符串。"""
    system = platform.system()
    try:
        if system == "Darwin":
            script = (
                'set chosenFolder to choose folder with prompt "选择工作目录"'
                "\nreturn POSIX path of chosenFolder"
            )
            r = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0:
                return r.stdout.strip()
        elif system == "Windows":
            ps_script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog;"
                "if ($f.ShowDialog() -eq 'OK') { Write-Output $f.SelectedPath }"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        else:
            for cmd in (["zenity", "--file-selection", "--directory"],
                        ["kdialog", "--getexistingdirectory", os.path.expanduser("~")]):
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if r.returncode == 0 and r.stdout.strip():
                        return r.stdout.strip()
                    break
                except FileNotFoundError:
                    continue
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.warning(f"[Workspace] Directory picker failed: {e}")
    return ""


@app.get("/api/voices")
async def get_voices():
    """返回可选 TTS 语音角色列表。"""
    return {"voices": AVAILABLE_VOICES}


@app.get("/api/comfyui/status")
async def comfyui_status():
    """Check the optional local ComfyUI service without affecting Agnes."""
    return await ComfyUIClient().health()


@app.post("/api/comfyui/generate")
async def comfyui_generate(request: Request):
    """Run the configured optional ComfyUI API workflow."""
    try:
        body = await request.json()
        client = ComfyUIClient()
        result = await client.generate(
            prompt=body.get("prompt"),
            seed=body.get("seed"),
            width=body.get("width"),
            height=body.get("height"),
            timeout=float(body.get("timeout", 1800)),
        )
        return {
            "provider": "comfyui",
            "prompt_id": result["prompt_id"],
            "outputs": result.get("outputs", []),
        }
    except (ComfyUIError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/comfyui/preview")
async def comfyui_preview(request: Request):
    """Validate/bind a ComfyUI API workflow without queueing it."""
    try:
        body = await request.json()
        workflow = build_workflow(
            prompt=body.get("prompt"),
            seed=body.get("seed"),
            width=body.get("width"),
            height=body.get("height"),
        )
        return {"valid": True, "workflow": workflow}
    except (ComfyUIError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ═══════════════════════════════════════════════════
# 简单图片生成（任务 + working_dir 持久化）
# ═══════════════════════════════════════════════════


@app.post("/api/image/generate")
async def generate_image(
    request: Request,
    prompt: str = Form(...),
    size: str = Form("1K"),
    ratio: str = Form("1:1"),
    negative_prompt: Optional[str] = Form(None),
    system_prompt: str = Form(""),
    reference_image: UploadFile = File(None),
):
    """简单图片生成：创建任务 → 直调 Agnes Image API → 保存到任务目录。"""

    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="Сначала настройте ключ API")

    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Промпт не может быть пустым")
    if len(prompt) > 5000:
        raise HTTPException(status_code=422, detail="Промпт может содержать не более 5000 символов")

    _VALID_SIZES = {"1K", "2K", "3K", "4K"}
    _VALID_RATIOS = {"1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9"}
    if size not in _VALID_SIZES:
        raise HTTPException(status_code=422, detail=f"Недопустимый размер изображения. Допустимые значения: {_VALID_SIZES}")
    if ratio not in _VALID_RATIOS:
        raise HTTPException(status_code=422, detail=f"Недопустимое соотношение сторон. Допустимые значения: {_VALID_RATIOS}")

    task_id = uuid.uuid4().hex[:12]
    name = f"image_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    state = SimpleImageTask(
        task_id=task_id,
        creative_name=name,
        prompt=prompt.strip(),
        size=size,
        negative_prompt=negative_prompt or "",
        system_prompt=system_prompt,
    )

    # 先用 PENDING 创建任务目录和状态文件
    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    _cache_task_dir(task_id, dir_name)

    image_api = AgnesImageAPI(api_key=api_key)

    ref_paths = []
    if reference_image and reference_image.filename:
        ref_paths.append(await _save_image_upload(reference_image, f"img_ref_{uuid.uuid4().hex[:8]}"))

    try:
        state.status = StepStatus.RUNNING
        tm.update_state(status=StepStatus.RUNNING)

        full_prompt = _build_image_prompt(system_prompt, prompt) if system_prompt.strip() else prompt
        output = await image_api.generate_single_image(
            prompt=full_prompt,
            reference_image_paths=ref_paths,
            size=size,
            ratio=ratio,
            negative_prompt=negative_prompt,
        )
    except Exception as e:
        state.status = StepStatus.FAILED
        tm.update_state(status=StepStatus.FAILED)
        logger.error(f"[Image] Task {task_id} failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Не удалось сгенерировать изображение. Проверьте API и повторите попытку.")
    finally:
        # Reference images for the one-shot image endpoint are temporary inputs;
        # the generated task does not retain them, so remove them after the API call.
        for ref_path in ref_paths:
            try:
                os.remove(ref_path)
            except OSError:
                logger.warning("[Image] Failed to remove temporary reference image: %s", ref_path)

    img_filename = "final_image.png"
    img_path = os.path.join(tm.task_dir, img_filename)
    try:
        output.save(img_path)
    except Exception as e:
        state.status = StepStatus.FAILED
        tm.update_state(status=StepStatus.FAILED)
        logger.error(f"[Image] Task {task_id} save failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Не удалось сохранить изображение на диск.")

    state.status = StepStatus.COMPLETED
    state.final_video_file = img_path
    tm.update_state(status=StepStatus.COMPLETED, final_video_file=img_path)

    logger.info(f"[Image] Task {task_id} completed: {img_path}, prompt={prompt[:60]}...")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.get("/api/image/{task_id}")
async def serve_image(task_id: str):
    """返回已生成的图片文件。"""
    dir_name = _find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state or not state.final_video_file:
        raise HTTPException(status_code=404, detail="Изображение не найдено")
    if not os.path.exists(state.final_video_file):
        raise HTTPException(status_code=404, detail="Файл изображения не найден")
    return FileResponse(state.final_video_file, media_type="image/png")


@app.get("/api/image/{task_id}/download")
async def download_image(task_id: str):
    """Скачать готовое изображение."""
    dir_name = _find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state or not state.final_video_file or not os.path.exists(state.final_video_file):
        raise HTTPException(status_code=404, detail="Изображение не найдено")
    return FileResponse(state.final_video_file, media_type="image/png", headers={"Content-Disposition": f'attachment; filename="image_{task_id}.png"'})


# ═══════════════════════════════════════════════════
# 任务列表 + 详情 + 视频下载
# ═══════════════════════════════════════════════════


@app.get("/api/tasks")
async def list_tasks():
    tasks = []
    for task_id, dir_name in sorted(_task_dir_cache.items(), key=lambda item: item[1], reverse=True):
        task_tm = TaskManager(task_id, dir_name=dir_name)
        state = task_tm.load()
        if not state:
            continue
        task = {
            "task_id": task_id,
            "dir_name": dir_name,
            "task_type": state.task_type,
            "creative_name": state.creative_name,
            "status": state.status,
            "chaining_mode": getattr(state, "chaining_mode", "none"),
            "final_video_file": state.final_video_file,
        }
        if isinstance(state, CreativeVideoTask):
            task["scene_count"] = state.scene_count
            task["idea"] = state.idea[:100] if state.idea else ""
        elif isinstance(state, ManuscriptVideoTask):
            task["paragraph_count"] = len(state.paragraphs)
            task["manuscript_text"] = state.manuscript_text[:100] if state.manuscript_text else ""
        elif isinstance(state, AnchorVideoTask):
            task["script_text"] = state.script_text[:100] if state.script_text else ""
            task["anchor_prompt"] = state.anchor_prompt[:100] if state.anchor_prompt else ""
            task["paragraph_count"] = len(state.paragraphs)
        elif isinstance(state, SimpleVideoTask):
            task["prompt"] = state.prompt[:100] if state.prompt else ""
            task["mode"] = state.mode
        elif isinstance(state, SimpleImageTask):
            task["prompt"] = state.prompt[:100] if state.prompt else ""
            task["size"] = state.size
        tasks.append(task)
    return {"tasks": tasks}



@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    dir_name = _find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    data = state.model_dump()
    data["dir_name"] = dir_name
    return data


@app.get("/api/video/{task_id}")
async def serve_video(task_id: str):
    dir_name = _find_dir_name(task_id)
    task_dir = os.path.join(get_working_dir(), dir_name)
    video_path = os.path.join(task_dir, "final_video.mp4")
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Видео не найдено")
    return FileResponse(video_path, media_type="video/mp4")


@app.get("/api/video/{task_id}/download")
async def download_video(task_id: str):
    """Скачать готовое видео."""
    dir_name = _find_dir_name(task_id)
    task_dir = os.path.join(get_working_dir(), dir_name)
    video_path = os.path.join(task_dir, "final_video.mp4")
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Видео не найдено")
    return FileResponse(video_path, media_type="video/mp4", headers={"Content-Disposition": f'attachment; filename="video_{task_id}.mp4"'})


# ═══════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════


# 时长提取 regex 模式（支持 7 种语言）
_DURATION_PATTERNS = [
    # 中文
    r'(?:每个场景|每段|每节|每个|每)(?:约)?(\d+)\s*(?:秒|s)',
    r'(\d+)\s*(?:秒|s)\s*(?:每|/)',
    # 日文
    r'各\s*(\d+)\s*秒',
    # 英文
    r'(\d+)\s*(?:seconds?|secs?|s)\s*(?:each|per)',
    r'(?:each|per)\s*(?:scene)?\s*(\d+)\s*(?:seconds?|secs?|s)',
    # 韩文
    r'각\s*(\d+)\s*초',
    # 俄文
    r'по\s*(\d+)\s*секунд',
    # 马来/印尼
    r'(\d+)\s*(?:saat|detik)\s*(?:setiap|masing)',
    r'(?:setiap|masing)\s*(?:satu\s+)?(\d+)\s*(?:saat|detik)',
    # 通用回退
    r'(\d+)\s*(?:秒|seconds?|secs?|초|секунд|saat|detik|s)\b',
]


def _parse_duration(user_requirement: str) -> int:
    """Extract a duration that is guaranteed to be a DURATION_FRAME_MAP key."""
    text_value = (user_requirement or "").strip()
    valid_duration_keys = sorted(DURATION_FRAME_MAP)
    if not valid_duration_keys:
        raise ValueError("DURATION_FRAME_MAP не содержит допустимых значений")
    default_duration = 5 if 5 in DURATION_FRAME_MAP else valid_duration_keys[0]
    for pattern in _DURATION_PATTERNS[:-1]:
        match = re.search(pattern, text_value, re.IGNORECASE)
        if match:
            value = int(match.group(1))
            if value in DURATION_FRAME_MAP:
                return value
            logger.warning(
                "[Duration] Unsupported requested duration %s; using %s",
                value, default_duration,
            )
            return default_duration
    return default_duration

def _has_explicit_duration(user_requirement: str) -> bool:
    """检查 user_requirement 中是否显式提到了时长。支持 7 种语言。"""
    text_value = (user_requirement or "").strip()
    return any(re.search(pattern, text_value, re.IGNORECASE) for pattern in _DURATION_PATTERNS[:-1])
    return False


def _build_image_prompt(system_prompt: str, user_prompt: str) -> str:
    """Combine system and user image instructions without prompt obfuscation."""
    system = (system_prompt or "").strip()
    user = (user_prompt or "").strip()
    if not system:
        return user
    if not user:
        return system
    return f"SYSTEM INSTRUCTIONS:\n{system}\n\nUSER IMAGE REQUEST:\n{user}"

def _make_progress_callback(task_id: str, ws: Optional[WebSocket] = None):
    """创建进度回调函数。优先使用传入的 ws，否则查找 active_connections。"""
    async def progress_callback(step: str, status: str, message: str, progress: float, data: dict):
        try:
            target_ws = ws or active_connections.get(task_id)
            if target_ws:
                await target_ws.send_json({
                    "type": "progress",
                    "task_id": task_id,
                    "step": step,
                    "status": status,
                    "message": message,
                    "progress": progress,
                    "data": data,
                })
        except Exception as e:
            logger.debug(f"[WS] Failed to send progress for {task_id}: {e}")
    return progress_callback


def _create_pipeline_for_type(
    task_type: TaskType,
    api_key: str,
    task_id: str,
    dir_name: str,
) -> BasePipeline:
    """根据任务类型创建对应的 Pipeline 实例。"""
    if task_type == TaskType.SIMPLE:
        return SimpleVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            shutdown_event=shutdown_event,
        )
    elif task_type == TaskType.MANUSCRIPT:
        return ManuscriptVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            shutdown_event=shutdown_event,
        )
    elif task_type == TaskType.ANCHOR:
        return AnchorPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            shutdown_event=shutdown_event,
        )
    else:
        # CREATIVE（默认）
        return CreativeVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            shutdown_event=shutdown_event,
        )


async def _run_pipeline(pipeline: BasePipeline, state: BaseTaskState):
    """通用 Pipeline 执行包装器。"""
    try:
        logger.info(f"[Pipeline] Starting run for task {pipeline.task_id}, type={state.task_type}")
        await pipeline.run(state)
        logger.info(f"[Pipeline] Completed run for task {pipeline.task_id}")
    except PipelineShutdown as e:
        logger.info(f"[Pipeline] Task {pipeline.task_id} stopped by user: {e}")
        # 更新任务状态为 FAILED，这样 UI 才会显示"续传"按钮
        try:
            _dir = _find_dir_name(pipeline.task_id)
            _tm = TaskManager(pipeline.task_id, dir_name=_dir)
            _tm.update_state(status=StepStatus.FAILED)
        except Exception as _ue:
            logger.debug(f"[Pipeline] Could not update status after shutdown: {_ue}")
    except Exception as e:
        logger.error(f"[Pipeline] Task {pipeline.task_id} failed: {e}", exc_info=True)
    finally:
        # 身份比对：仅当字典里仍是当前 pipeline 时才删除。
        # 否则快速 resume→stop 会让旧 pipeline 的 finally 误删新 pipeline。
        if active_pipelines.get(pipeline.task_id) is pipeline:
            del active_pipelines[pipeline.task_id]
            _pipeline_locks.pop(pipeline.task_id, None)


async def _run_pipeline_with_concurrency(
    pipeline: BasePipeline,
    state: BaseTaskState,
    task_manager: TaskManager,
):
    """带并发控制的 Pipeline 执行包装器。

    复用回归流程的加权信号量逻辑：
    1. 先将任务标记为 queued（排队中）
    2. 等待加权信号量（总并发权重 ≤ MAX_CONCURRENT_WEIGHT）
    3. 获取到信号量后启动 pipeline
    4. pipeline 结束后释放信号量
    """
    weight = TASK_TYPE_WEIGHTS.get(state.task_type, 1)
    task_id = pipeline.task_id
    _queued_tasks[task_id] = weight

    logger.info(
        f"[Concurrency] Task {task_id} queued (weight={weight}, "
        f"current={_pipeline_semaphore.current}/{_pipeline_semaphore.max_weight})"
    )

    acquired = False

    try:
        # Mark the task queued inside the protected section so an exception while
        # persisting state still reaches the cleanup in finally.
        task_manager.update_state(status=StepStatus.QUEUED)

        # 等待并发槽位
        await _pipeline_semaphore.acquire(weight)
        acquired = True
        # 已获取槽位，从排队列表移除
        _queued_tasks.pop(task_id, None)

        logger.info(
            f"[Concurrency] Task {task_id} acquired slot (weight={weight}, "
            f"current={_pipeline_semaphore.current}/{_pipeline_semaphore.max_weight})"
        )

        # 检查是否在排队期间被 stop
        if getattr(pipeline, '_stop_event', None) and pipeline._stop_event.is_set():
            logger.info(f"[Concurrency] Task {task_id} was stopped while queued, skipping")
            try:
                task_manager.update_state(status=StepStatus.PENDING)
            except Exception:
                logger.exception("[Concurrency] Failed to persist stopped queued task %s", task_id)
            return

        # 启动 pipeline
        await _run_pipeline(pipeline, state)
    except asyncio.CancelledError:
        _queued_tasks.pop(task_id, None)
        # Only a task still waiting for a slot can remain QUEUED. Do not overwrite
        # the state of a task that was already running when cancellation arrived.
        if not acquired:
            try:
                task_manager.update_state(status=StepStatus.PENDING)
            except Exception:
                logger.exception("[Concurrency] Failed to persist cancelled queued task %s", task_id)
        logger.info(f"[Concurrency] Task {task_id} cancelled")
        raise
    finally:
        if acquired:
            try:
                await _pipeline_semaphore.release(weight)
                logger.info(
                    f"[Concurrency] Task {task_id} released slot (weight={weight}, "
                    f"current={_pipeline_semaphore.current}/{_pipeline_semaphore.max_weight})"
                )
            except Exception:
                logger.exception("[Concurrency] Failed to release slot for %s", task_id)
        _queued_tasks.pop(task_id, None)
        if active_pipelines.get(task_id) is pipeline:
            active_pipelines.pop(task_id, None)
            _pipeline_locks.pop(task_id, None)
        elif task_id not in active_pipelines:
            _pipeline_locks.pop(task_id, None)


def _launch_background_task(coro):
    """Launch a background task with a strong reference to prevent GC."""
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return task


# ═══════════════════════════════════════════════════
# 任务创建端点 — 三种类型
# ═══════════════════════════════════════════════════


@app.post("/api/tasks/simple")
async def create_simple_task(
    request: Request,
    prompt: str = Form(...),
    model: str = Form("agnes-video-2.5-flash"),
    mode: str = Form("t2v"),
    duration: int = Form(5),
    video_width: int = Form(1152),
    video_height: int = Form(648),
    seed: Optional[int] = Form(None),
    negative_prompt: Optional[str] = Form(None),
    system_prompt: str = Form(""),
    reference_image: UploadFile = File(None),
    end_frame_image: UploadFile = File(None),
):
    """创建简单视频任务（类型 1）。"""

    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="Сначала настройте ключ API")

    # P7: 参数校验
    if model not in {"agnes-video-2.5-flash", "agnes-video-2.5"}:
        raise HTTPException(status_code=422, detail="Неподдерживаемая модель видео")
    _validate_video_dimensions(video_width, video_height)
    _VALID_MODES = {"t2v", "i2v", "ti2vid", "keyframes"}
    if mode not in _VALID_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"mode 必须为 {_VALID_MODES} 之一，当前: {mode}",
        )
    if duration not in SUPPORTED_AGNES_VIDEO_DURATIONS:
        raise HTTPException(
            status_code=422,
            detail=f"duration должен быть одним из {sorted(SUPPORTED_AGNES_VIDEO_DURATIONS)}, сейчас: {duration}",
        )
    if len(prompt) > 5000:
        raise HTTPException(status_code=422, detail="Промпт может содержать не более 5000 символов")

    task_id = uuid.uuid4().hex[:12]
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # 映射模式
    video_mode = VideoMode.T2V
    if mode in ("i2v", "ti2vid"):
        video_mode = VideoMode.I2V if mode == "i2v" else VideoMode.TI2VID
    elif mode == "keyframes":
        video_mode = VideoMode.KEYFRAMES

    state = SimpleVideoTask(
        task_id=task_id,
        creative_name=f"simple_{task_id}",
        prompt=prompt,
        model=model,
        mode=video_mode,
        duration=duration,
        video_width=video_width,
        video_height=video_height,
        seed=seed,
        negative_prompt=negative_prompt,
        system_prompt=system_prompt,
    )

    # 处理参考图上传（L4: 用 UUID 替代客户端文件名，避免路径穿越）
    if reference_image and reference_image.filename:
        state.reference_image = await _save_image_upload(reference_image, f"{task_id}_ref")

    # 处理尾帧图上传（keyframes 模式）
    if end_frame_image and end_frame_image.filename:
        state.end_frame_image = await _save_image_upload(end_frame_image, f"{task_id}_end")

    pipeline = _create_pipeline_for_type(TaskType.SIMPLE, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline
    _cache_task_dir(task_id, dir_name)

    if task_id in active_connections:
        pipeline.progress_callback = _make_progress_callback(task_id)

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Simple] Task created: {task_id}, mode={mode}, duration={duration}s (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.post("/api/tasks/creative")
async def create_creative_task(
    request: Request,
    idea: str = Form(...),
    creative_name: str = Form(""),
    style: str = Form("电影质感写实风格"),
    negative_prompt: str = Form(""),
    include_characters: bool = Form(True),
    chaining_mode: str = Form("keyframes"),
    video_width: int = Form(1152),
    video_height: int = Form(648),
    # ── v3.x 场景配置 ──
    duration_source: str = Form("manual"),
    scene_count: int = Form(3),
    uniform_duration: bool = Form(True),
    scene_durations_json: str = Form("[5,5,5]"),
    reference_image: UploadFile = File(None),
    end_frame_images: List[UploadFile] = File(None),
    use_custom_end_frames: bool = Form(False),
    generate_end_frames_from_ref: bool = Form(True),
    # v2.0 音频配置
    audio_enabled: bool = Form(False),
    audio_voice: str = Form("ru-RU-SvetlanaNeural"),
    audio_rate: str = Form("+0%"),
    # v3.0 字幕独立配置
    subtitle_enabled: bool = Form(True),
    subtitle_style_mode: str = Form("fixed"),
    subtitle_style_hints: str = Form(""),
    subtitle_font: str = Form("STHeitiMedium.ttc"),
    subtitle_color: str = Form("white"),
    subtitle_fontsize: int = Form(48),
    subtitle_position: str = Form("bottom"),
    subtitle_stroke_color: str = Form("black"),
    subtitle_stroke_width: int = Form(2),
    subtitle_bg_color: str = Form("black@0.5"),
):
    """创建创意长视频任务（类型 2）。"""

    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="Сначала настройте ключ API")

    # P7: 参数校验
    _validate_video_dimensions(video_width, video_height)
    if chaining_mode not in ("independent", "ti2vid", "keyframes"):
        raise HTTPException(status_code=422, detail="Неподдерживаемый режим связности сцен")
    if len(idea) > 10000:
        raise HTTPException(status_code=422, detail="Идея может содержать не более 10000 символов")
    if duration_source not in ("manual", "prompt"):
        raise HTTPException(status_code=422, detail="Источник длительности должен быть ручным или заданным в промпте")
    if duration_source == "manual":
        if scene_count < 1 or scene_count > 30:
            raise HTTPException(status_code=422, detail="Количество сцен должно быть от 1 до 30")
        # 解析场景时长 JSON
        try:
            scene_durations = json.loads(scene_durations_json)
            if not isinstance(scene_durations, list):
                raise ValueError("not a list")
            if len(scene_durations) != scene_count:
                raise ValueError("length mismatch")
        except Exception:
            raise HTTPException(status_code=422, detail="Параметры длительности сцен должны быть массивом JSON")
        # 校验每个时长
        for i, d in enumerate(scene_durations):
            if not isinstance(d, (int, float)) or d < 4 or d > 12:
                raise HTTPException(status_code=422, detail=f"Длительность сцены {i+1} должна быть от 4 до 12 секунд (ограничение Agnes Video 2.5)")
    else:
        scene_durations = []

    task_id = uuid.uuid4().hex[:12]
    name = creative_name.strip() if creative_name else f"video_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # 构建音频配置
    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
    )
    # 构建独立字幕配置（v3.0）
    subtitle_style = SubtitleStyle(
        font=subtitle_font,
        color=subtitle_color,
        fontsize=subtitle_fontsize,
        position=_build_position(subtitle_position),
        stroke_color=subtitle_stroke_color,
        stroke_width=subtitle_stroke_width,
        bg_color=_parse_bg_color(subtitle_bg_color),
        style_mode=subtitle_style_mode,
        style_hints=subtitle_style_hints,
    )
    subtitle_config = SubtitleConfig(
        enabled=subtitle_enabled,
        style=subtitle_style,
    )

    state = CreativeVideoTask(
        task_id=task_id,
        creative_name=name,
        idea=idea,
        style=style,
        negative_prompt=negative_prompt,
        include_characters=include_characters,
        chaining_mode=chaining_mode,
        video_width=video_width,
        video_height=video_height,
        video_duration=5,
        duration_source=duration_source,
        scene_count=scene_count,
        uniform_duration=uniform_duration,
        scene_durations=scene_durations,
        use_custom_end_frames=use_custom_end_frames,
        generate_end_frames_from_ref=generate_end_frames_from_ref,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
    )

    logger.info(
        f"[Pipeline] Scene config: source={duration_source}, "
        f"scenes={scene_count}, durations={scene_durations}, uniform={uniform_duration}"
    )

    # 处理参考图上传（L4: 用 UUID 替代客户端文件名，避免路径穿越）
    if reference_image and reference_image.filename:
        state.reference_image = await _save_image_upload(reference_image, f"{task_id}_ref")


    # P3: 处理自定义尾帧图片上传
    if use_custom_end_frames and end_frame_images:
        saved_paths = []
        for idx, ef_file in enumerate(end_frame_images):
            if ef_file and ef_file.filename:
                saved_paths.append(await _save_image_upload(ef_file, f"{task_id}_end_{idx}"))
        if saved_paths:
            state.end_frame_images = saved_paths
            logger.info(f"[Pipeline] Saved {len(saved_paths)} custom end frame images for task {task_id}")

    pipeline = _create_pipeline_for_type(TaskType.CREATIVE, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    if task_id in active_connections:
        pipeline.progress_callback = _make_progress_callback(task_id)

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    _cache_task_dir(task_id, dir_name)
    _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Creative] Task created: {task_id}, idea={idea[:40]}... (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.post("/api/tasks/manuscript")
async def create_manuscript_task(
    request: Request,
    manuscript_text: str = Form(...),
    video_style: str = Form(""),
    negative_prompt: str = Form(""),
    creative_name: str = Form(""),
    video_width: int = Form(1152),
    video_height: int = Form(648),
    video_duration: int = Form(10),
    # v2.0 音频配置
    audio_enabled: bool = Form(True),
    audio_voice: str = Form("ru-RU-SvetlanaNeural"),
    audio_rate: str = Form("+0%"),
    # v3.0 字幕独立配置
    subtitle_enabled: bool = Form(True),
    subtitle_style_mode: str = Form("fixed"),
    subtitle_style_hints: str = Form(""),
    subtitle_font: str = Form("STHeitiMedium.ttc"),
    subtitle_color: str = Form("white"),
    subtitle_fontsize: int = Form(48),
    subtitle_position: str = Form("bottom"),
    subtitle_stroke_color: str = Form("black"),
    subtitle_stroke_width: int = Form(2),
    subtitle_bg_color: str = Form("black@0.5"),
):
    """创建稿件长视频任务（类型 3）。"""

    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="Сначала настройте ключ API")

    _validate_video_dimensions(video_width, video_height)
    if not manuscript_text.strip():
        raise HTTPException(status_code=400, detail="Текст сценария не может быть пустым")
    # P7: 文本长度上限
    if len(manuscript_text) > 50000:
        raise HTTPException(status_code=422, detail="Текст сценария может содержать не более 50000 символов")

    task_id = uuid.uuid4().hex[:12]
    name = creative_name.strip() if creative_name else f"manuscript_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # 构建音频配置
    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
    )
    # 构建独立字幕配置（v3.0）
    subtitle_style = SubtitleStyle(
        font=subtitle_font,
        color=subtitle_color,
        fontsize=subtitle_fontsize,
        position=_build_position(subtitle_position),
        stroke_color=subtitle_stroke_color,
        stroke_width=subtitle_stroke_width,
        bg_color=_parse_bg_color(subtitle_bg_color),
        style_mode=subtitle_style_mode,
        style_hints=subtitle_style_hints,
    )
    subtitle_config = SubtitleConfig(
        enabled=subtitle_enabled,
        style=subtitle_style,
    )

    state = ManuscriptVideoTask(
        task_id=task_id,
        creative_name=name,
        manuscript_text=manuscript_text.strip(),
        video_style=video_style.strip(),
        negative_prompt=negative_prompt.strip(),
        video_width=video_width,
        video_height=video_height,
        video_duration=video_duration,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
    )

    pipeline = _create_pipeline_for_type(TaskType.MANUSCRIPT, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    if task_id in active_connections:
        pipeline.progress_callback = _make_progress_callback(task_id)

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    _cache_task_dir(task_id, dir_name)
    _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Manuscript] Task created: {task_id}, text_len={len(manuscript_text)} (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.post("/api/tasks/anchor")
async def create_anchor_task(
    request: Request,
    anchor_prompt: str = Form(""),
    anchor_reference_image: UploadFile = File(None),
    script_text: str = Form(...),
    negative_prompt: str = Form(""),
    audio_source: str = Form("post_stitch"),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    audio_enabled: bool = Form(True),
    audio_voice: str = Form("ru-RU-SvetlanaNeural"),
    audio_rate: str = Form("+0%"),
    subtitle_enabled: bool = Form(True),
    subtitle_style_mode: str = Form("fixed"),
    subtitle_style_hints: str = Form(""),
    subtitle_font: str = Form("STHeitiMedium.ttc"),
    subtitle_color: str = Form("white"),
    subtitle_fontsize: int = Form(42),
    subtitle_position: str = Form("bottom"),
    subtitle_stroke_color: str = Form("black"),
    subtitle_stroke_width: int = Form(2),
    subtitle_bg_color: str = Form("black@0.5"),
):
    """创建数字人口播任务（类型 4 / Phase 3）。"""

    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="Сначала настройте ключ API")

    if not script_text.strip():
        raise HTTPException(status_code=400, detail="Текст для озвучки не может быть пустым")
    if len(script_text) > 50000:
        raise HTTPException(status_code=422, detail="Текст для озвучки может содержать не более 50000 символов")

    task_id = uuid.uuid4().hex[:12]
    name = f"anchor_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
    )
    subtitle_style = SubtitleStyle(
        font=subtitle_font,
        color=subtitle_color,
        fontsize=subtitle_fontsize,
        position=_build_position(subtitle_position),
        stroke_color=subtitle_stroke_color,
        stroke_width=subtitle_stroke_width,
        bg_color=_parse_bg_color(subtitle_bg_color),
        style_mode=subtitle_style_mode,
        style_hints=subtitle_style_hints,
    )
    subtitle_config = SubtitleConfig(
        enabled=subtitle_enabled,
        style=subtitle_style,
    )

    # 处理参考图上传
    ref_image_path = ""
    if anchor_reference_image and anchor_reference_image.filename:
        ref_image_path = await _save_image_upload(anchor_reference_image, f"{task_id}_ref")

    state = AnchorVideoTask(
        task_id=task_id,
        creative_name=name,
        anchor_prompt=anchor_prompt,
        anchor_reference_image=ref_image_path,
        script_text=script_text.strip(),
        negative_prompt=negative_prompt.strip(),
        audio_source=audio_source,
        video_width=video_width,
        video_height=video_height,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
    )

    pipeline = _create_pipeline_for_type(TaskType.ANCHOR, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    if task_id in active_connections:
        pipeline.progress_callback = _make_progress_callback(task_id)

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    _cache_task_dir(task_id, dir_name)
    _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Anchor] Task created: {task_id}, script_len={len(script_text)} (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


# ═══════════════════════════════════════════════════
# 向后兼容：旧的 POST /api/tasks → 映射到 creative
# ═══════════════════════════════════════════════════


@app.post("/api/tasks")
async def create_task_legacy(
    request: Request,
    idea: str = Form(...),
    creative_name: str = Form(""),
    user_requirement: str = Form("3个场景，每个场景10秒，电影质感"),
    style: str = Form("电影质感写实风格"),
    chaining_mode: str = Form("keyframes"),
    video_width: int = Form(1152),
    video_height: int = Form(648),
    reference_image: UploadFile = File(None),
    end_frame_images: List[UploadFile] = File(None),
    use_custom_end_frames: bool = Form(False),
    generate_end_frames_from_ref: bool = Form(True),
):
    """向后兼容旧端点，映射到 create_creative_task。"""
    return await create_creative_task(
        request=request,
        idea=f"{idea}\n{user_requirement}",
        creative_name=creative_name,
        style=style,
        chaining_mode=chaining_mode,
        video_width=video_width,
        video_height=video_height,
        reference_image=reference_image,
        end_frame_images=end_frame_images,
        use_custom_end_frames=use_custom_end_frames,
        generate_end_frames_from_ref=generate_end_frames_from_ref,
        duration_source="prompt",
        scene_count=3,
        scene_durations_json="[5,5,5]",
        audio_enabled=False,
        audio_voice="ru-RU-SvetlanaNeural",
        audio_rate="+0%",
        subtitle_enabled=True,
        subtitle_font="STHeitiMedium.ttc",
        subtitle_color="white",
        subtitle_fontsize=48,
        subtitle_position="bottom",
        subtitle_stroke_color="black",
        subtitle_stroke_width=2,
        subtitle_bg_color="black@0.5",
    )


# ═══════════════════════════════════════════════════
# 任务恢复 + 停止
# ═══════════════════════════════════════════════════


@app.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: str, request: Request):
    _validate_task_id(task_id)
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="Сначала настройте ключ API")

    # 关键段串行化：check 与 insert 之间存在多个 await 让出点，快速重复 resume
    # 会让两次请求都通过 "task not in active_pipelines" 检查并各自启动 pipeline，
    # 导致同任务双重运行、状态文件交叉写入。
    async with _get_pipeline_lock(task_id):
        if task_id in active_pipelines:
            existing = active_pipelines[task_id]
            if existing._stop_event.is_set():
                logger.info(f"[Resume] Replacing stopped pipeline for task {task_id}")
                del active_pipelines[task_id]
            else:
                raise HTTPException(status_code=400, detail="Задача уже выполняется")

        dir_name = _find_dir_name(task_id)
        tm = TaskManager(task_id, dir_name=dir_name)
        state = tm.load()
        if not state:
            raise HTTPException(status_code=404, detail="Задача не найдена")

        if state.status == StepStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="Задача уже завершена")

        logger.info(f"[Resume] Starting resume for task {task_id}, type={state.task_type}, status={state.status}")

        # v2.0：根据 task_type 选择对应的 Pipeline
        pipeline = _create_pipeline_for_type(state.task_type, api_key, task_id, dir_name)
        active_pipelines[task_id] = pipeline

        if task_id in active_connections:
            logger.info(f"[Resume] Binding existing WebSocket for task {task_id}")
            pipeline.progress_callback = _make_progress_callback(task_id)

        _launch_background_task(_run_pipeline_with_concurrency(pipeline, state, tm))
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str, request: Request):
    _validate_task_id(task_id)
    async with _get_pipeline_lock(task_id):
        if task_id not in active_pipelines and task_id not in _queued_tasks:
            raise HTTPException(status_code=400, detail="Задача не выполняется")

        pipeline = active_pipelines.get(task_id)
        if pipeline is not None:
            pipeline.stop()

        dir_name = _find_dir_name(task_id)
        tm = TaskManager(task_id, dir_name=dir_name)
        state = tm.load()
        if state and state.status in (StepStatus.RUNNING, StepStatus.QUEUED):
            tm.update_state(status=StepStatus.PENDING)
            logger.info(f"[Stop] Task {task_id} status -> pending")

        logger.info(f"[Stop] Task {task_id} stop requested")
        return {"ok": True, "task_id": task_id}

# ═══════════════════════════════════════════════════
# 并发状态接口
# ═══════════════════════════════════════════════════


@app.get("/api/concurrency")
async def get_concurrency_status(request: Request):
    """返回当前并发控制状态：已用权重、上限、排队任务列表。"""
    running_tasks = []
    for tid, pl in active_pipelines.items():
        if tid not in _queued_tasks:
            # 真正在运行的（已获取信号量）
            running_tasks.append({
                "task_id": tid,
                "type": getattr(pl, '_task_type', 'unknown'),
            })

    queued = [
        {"task_id": tid, "weight": w}
        for tid, w in _queued_tasks.items()
    ]

    return {
        "ok": True,
        "max_weight": _pipeline_semaphore.max_weight,
        "current_weight": _pipeline_semaphore.current,
        "utilization": round(_pipeline_semaphore.utilization, 2),
        "running_count": len(running_tasks),
        "queued_count": len(queued),
        "queued_tasks": queued,
        "rate_limit_per_min": _AGNES_RATE_LIMIT,
        "task_weights": {k.value: v for k, v in TASK_TYPE_WEIGHTS.items()},
    }


# ═══════════════════════════════════════════════════
# 回归测试清理
# ═══════════════════════════════════════════════════

@app.post("/api/cleanup-regression")
async def cleanup_regression(request: Request):
    """安全清理回归测试产物（报告、日志、任务目录）。

    只删除产物清单中记录的内容，不影响用户原有任务数据。
    """
    working_dir = get_working_dir()
    manifest_path = os.path.join(working_dir, ".regression_manifest.json")

    if not os.path.exists(manifest_path):
        raise HTTPException(
            status_code=404,
            detail="Список результатов тестирования не найден. Возможно, тестирование ещё не выполнялось")

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("[Cleanup] Failed to read regression manifest", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Не удалось прочитать список результатов тестирования.") from e

    removed_dirs = 0
    removed_files = 0
    errors: list = []
    project_root = os.path.dirname(os.path.abspath(__file__))
    upload_dir = os.path.join(working_dir, "uploads")

    # 1. 清理任务目录
    for dir_name in manifest.get("task_dirs", []):
        dir_path = os.path.join(working_dir, dir_name)
        if os.path.isdir(dir_path):
            try:
                shutil.rmtree(dir_path)
                removed_dirs += 1
            except OSError as e:
                errors.append(f"删除目录失败 {dir_name}: {e}")

    # 2. 清理上传文件
    for fname in manifest.get("uploads", []):
        fpath = os.path.join(upload_dir, fname)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
                removed_files += 1
            except OSError as e:
                errors.append(f"删除上传文件失败 {fname}: {e}")

    # 3. 清理报告文件
    for rel_path in manifest.get("reports", []):
        abs_path = os.path.join(project_root, rel_path)
        if os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
                removed_files += 1
            except OSError as e:
                errors.append(f"删除报告失败 {rel_path}: {e}")

    # 4. 清理服务器日志
    log_rel = manifest.get("server_log", "")
    if log_rel:
        log_path = os.path.join(project_root, log_rel)
        if os.path.isfile(log_path):
            try:
                os.remove(log_path)
                removed_files += 1
            except OSError as e:
                errors.append(f"删除日志失败: {e}")

    # 5. 清理清单本身
    try:
        os.remove(manifest_path)
        removed_files += 1
    except OSError as e:
        errors.append(f"删除清单失败: {e}")

    scenarios_cleaned = len(manifest.get("scenarios", {}))
    logger.info(
        f"[Cleanup] 回归清理完成: {removed_dirs} 目录, "
        f"{removed_files} 文件, {scenarios_cleaned} 场景")

    return {
        "ok": len(errors) == 0,
        "removed_dirs": removed_dirs,
        "removed_files": removed_files,
        "scenarios_cleaned": scenarios_cleaned,
        "errors": errors,
    }


# ═══════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════


if __name__ == "__main__":
    import uvicorn

    config = uvicorn.Config(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8765")), log_level="info")
    server = uvicorn.Server(config)

    original_handle_exit = server.handle_exit

    def _handle_exit(sig, frame):
        if shutdown_event.is_set():
            logger.warning("Force exiting...")
            os._exit(1)
        logger.info("Shutting down gracefully (Ctrl+C again to force)...")
        shutdown_event.set()
        if callable(original_handle_exit):
            original_handle_exit(sig, frame)

    server.handle_exit = _handle_exit

    server.run()
