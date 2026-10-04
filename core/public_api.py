"""Public AISTUDIO API backed by Agnes AI.

The public workspace is intentionally a thin UI over the user's Agnes API key.
No Google/Gemini credentials are required for the public image/video routes.
"""
import os, tempfile, asyncio, secrets
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.public_store import (
    init_db, create_user, authenticate, create_session, get_user_by_session,
    revoke_session, ledger, change_credits, add_generation, generations,
    update_generation,
)
from core.config import get_api_key
from core.api.agnes_image import AgnesImageAPI
from core.api.agnes_video import AgnesVideoAPI

router = APIRouter(prefix="/api/public", tags=["public"])
init_db()


class AuthBody(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=200)


def token(request):
    return request.cookies.get("ai_session") or request.headers.get(
        "Authorization", ""
    ).removeprefix("Bearer ").strip()


def user(request):
    u = get_user_by_session(token(request))
    if not u:
        raise HTTPException(401, "Требуется вход")
    return u


def _agnes_key() -> str:
    key = get_api_key()
    if not key:
        raise HTTPException(
            503,
            "AGNES_API_KEY не настроен на сервере Render"
        )
    return key


def _reference_file(data: bytes, filename: str):
    suffix = os.path.splitext(filename or "")[1].lower() or ".png"
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(415, "Поддерживаются PNG, JPG и WebP")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Изображение слишком большое (максимум 10 МБ)")
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="ai_ref_")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(data)
    return path


@router.post("/guest")
def guest():
    # Create an invisible guest account so generation works without manual login.
    email = "guest-" + secrets.token_hex(12) + "@local.invalid"
    password = secrets.token_urlsafe(32)
    uid, _ = create_user(email, password)
    return {"ok": True, "token": create_session(uid), "guest": True, "credits": None}


@router.post("/register")
def register(body: AuthBody):
    try:
        uid, email = create_user(body.email, body.password)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "token": create_session(uid), "email": email, "credits": None}


@router.post("/login")
def login(body: AuthBody):
    found = authenticate(body.email, body.password)
    if not found:
        raise HTTPException(401, "Неверный email или пароль")
    uid, email = found
    return {"ok": True, "token": create_session(uid), "email": email, "credits": None}


@router.post("/logout")
def logout(request: Request):
    revoke_session(token(request))
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    u = user(request)
    return {**u, "credits": None, "billing": "agnes"}


@router.get("/ledger")
def get_ledger(request: Request):
    return {"items": ledger(user(request)["id"])}


@router.get("/history")
def get_history(request: Request):
    return {"items": generations(user(request)["id"])}


@router.get("/generation/{generation_id}/output")
def generation_output(generation_id: str, request: Request):
    u = user(request)
    item = next((x for x in generations(u["id"]) if x["id"] == generation_id), None)
    if not item:
        raise HTTPException(404, "Генерация не найдена")
    if item["status"] != "completed" or not item.get("output_path"):
        raise HTTPException(409, "Результат ещё не готов")
    path = item["output_path"]
    if not os.path.isfile(path):
        raise HTTPException(410, "Файл результата больше недоступен")
    media = "video/mp4" if item["type"] == "video" else "image/png"
    return FileResponse(path, media_type=media)


@router.get("/models")
def models():
    # These are Agnes models. The public UI no longer routes through Google/Veo.
    return {"models": [
        {
            "id": "agnes-image-2.1-flash",
            "name": "Agnes Image 2.1 Flash",
            "provider": "Agnes AI",
            "type": "image",
            "credits": 0,
            "status": "ready",
            "description": "Генерация и редактирование изображений",
        },
        {
            "id": "agnes-image-2.0-flash",
            "name": "Agnes Image 2.0 Flash",
            "provider": "Agnes AI",
            "type": "image",
            "credits": 0,
            "status": "ready",
            "description": "Быстрая генерация изображений",
        },
        {
            "id": "agnes-video-v2.0",
            "name": "Agnes Video v2.0",
            "provider": "Agnes AI",
            "type": "video",
            "credits": 0,
            "status": "ready",
            "description": "Text-to-video и image-to-video",
        },
    ]}


@router.post("/generate/image")
async def generate_image(
    request: Request,
    prompt: str = Form(...),
    model: str = Form("agnes-image-2.1-flash"),
    reference: UploadFile = File(None),
):
    u = user(request)
    allowed = {"agnes-image-2.1-flash", "agnes-image-2.0-flash"}
    if model not in allowed:
        raise HTTPException(400, "Эта модель пока недоступна")
    if not prompt.strip():
        raise HTTPException(422, "Промпт не может быть пустым")

    ref = []
    try:
        if reference and reference.filename:
            ref.append(_reference_file(await reference.read(), reference.filename))

        provider = AgnesImageAPI(
            api_key=_agnes_key(),
            model=model,
            i2i_model=model,
        )
        output = await provider.generate_single_image(
            prompt.strip(),
            reference_image_paths=ref,
            size="1024x1024",
        )

        path = os.path.join(
            tempfile.gettempdir(), "ai_studio_agnes_%s.png" % os.urandom(8).hex()
        )
        output.save(path)
        generation_id = add_generation(
            u["id"], model, "image", prompt.strip(), "completed", path, 0
        )
        return FileResponse(
            path,
            media_type="image/png",
            headers={"X-Credits-Remaining": "unlimited", "X-Generation-Id": generation_id},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Agnes: генерация изображения не выполнена: {e}")
    finally:
        for path in ref:
            try:
                os.remove(path)
            except OSError:
                pass


def _video_dimensions(aspect_ratio: str):
    return {
        "16:9": (1152, 648),
        "9:16": (648, 1152),
    }.get(aspect_ratio, (1152, 648))


async def _run_video_generation(
    user_id, generation_id, prompt, reference_path=None,
    aspect_ratio="16:9", resolution="720p", model="agnes-video-v2.0"
):
    try:
        width, height = _video_dimensions(aspect_ratio)
        # Agnes v2.0 currently uses width/height + num_frames/frame_rate.
        # 720p is the safe public default; the provider caps frames to API limits.
        provider = AgnesVideoAPI(
            api_key=get_api_key(),
            model=model,
            default_duration=5,
            max_retries=3,
            retry_base_delay=20,
        )
        output = await provider.generate_single_video(
            prompt,
            reference_image_paths=[reference_path] if reference_path else [],
            duration=5,
            width=width,
            height=height,
        )
        path = os.path.join(
            tempfile.gettempdir(), "ai_studio_agnes_%s.mp4" % os.urandom(8).hex()
        )
        output.save(path)
        update_generation(generation_id, "completed", path)
    except Exception:
        update_generation(generation_id, "failed", None)
    finally:
        if reference_path:
            try:
                os.remove(reference_path)
            except OSError:
                pass


@router.post("/generate/video")
async def generate_video(
    request: Request,
    prompt: str = Form(...),
    model: str = Form("agnes-video-v2.0"),
    aspect_ratio: str = Form("16:9"),
    resolution: str = Form("720p"),
    reference: UploadFile = File(None),
):
    u = user(request)
    _agnes_key()
    if model != "agnes-video-v2.0":
        raise HTTPException(400, "Эта модель пока недоступна")
    if not prompt.strip():
        raise HTTPException(422, "Промпт не может быть пустым")
    if aspect_ratio not in {"16:9", "9:16"}:
        raise HTTPException(422, "Неподдерживаемое соотношение сторон")

    ref_path = None
    try:
        if reference and reference.filename:
            ref_path = _reference_file(await reference.read(), reference.filename)

        generation_id = add_generation(
            u["id"], model, "video", prompt.strip(), "processing", None, 0
        )
        asyncio.create_task(
            _run_video_generation(
                u["id"], generation_id, prompt.strip(), ref_path,
                aspect_ratio, resolution, model
            )
        )
        ref_path = None
        return {
            "ok": True,
            "generation_id": generation_id,
            "status": "processing",
            "credits": None,
            "billing": "Agnes AI",
        }
    except HTTPException:
        raise
    except Exception as e:
        if ref_path:
            try:
                os.remove(ref_path)
            except OSError:
                pass
        raise HTTPException(502, f"Не удалось запустить Agnes Video: {e}")
