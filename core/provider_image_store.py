"""Short-lived, opaque URLs for images that legacy Agnes Video must fetch publicly."""
import mimetypes
import os
import secrets
import time
from urllib.parse import urlsplit

from core.config import get_working_dir

_TTL_SECONDS = 2 * 60 * 60
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_tokens: dict[str, tuple[str, float]] = {}


def _safe_image_path(path: str) -> str:
    resolved = os.path.realpath(path)
    root = os.path.realpath(get_working_dir())
    try:
        inside_root = os.path.commonpath((root, resolved)) == root
    except ValueError:
        inside_root = False
    if not inside_root or not os.path.isfile(resolved):
        raise ValueError("Референс должен быть существующим файлом внутри рабочего каталога")
    if os.path.splitext(resolved)[1].lower() not in _IMAGE_EXTENSIONS:
        raise ValueError("Для передачи в Agnes поддерживаются PNG, JPG и WEBP")
    return resolved


def create_provider_image_url(path: str) -> str:
    """Register an image and return an unguessable, expiring HTTPS URL."""
    configured = (
        os.environ.get("AGNES_PUBLIC_BASE_URL", "").strip()
        or os.environ.get("PUBLIC_BASE_URL", "").strip()
    )
    if configured:
        parsed = urlsplit(configured if "://" in configured else "https://" + configured)
        if parsed.scheme != "https" or not parsed.netloc:
            raise RuntimeError("AGNES_PUBLIC_BASE_URL должен быть публичным HTTPS-адресом")
        base_url = f"https://{parsed.netloc}"
    else:
        hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
        if not hostname:
            raise RuntimeError(
                "Не задан публичный адрес сервера: legacy Agnes не может получить локальный файл. "
                "На Render ожидается RENDER_EXTERNAL_HOSTNAME."
            )
        parsed = urlsplit(hostname if "://" in hostname else "https://" + hostname)
        if parsed.scheme != "https" or not parsed.netloc:
            raise RuntimeError("RENDER_EXTERNAL_HOSTNAME не является корректным публичным HTTPS-адресом")
        base_url = f"https://{parsed.netloc}"

    safe_path = _safe_image_path(path)
    now = time.time()
    for token, (_, expires_at) in list(_tokens.items()):
        if expires_at <= now:
            _tokens.pop(token, None)
    token = secrets.token_urlsafe(32)
    _tokens[token] = (safe_path, now + _TTL_SECONDS)
    return f"{base_url}/api/provider-image/{token}"


def resolve_provider_image(token: str) -> str | None:
    """Resolve an unexpired token without exposing arbitrary filesystem paths."""
    if not token or len(token) > 128:
        return None
    entry = _tokens.get(token)
    if not entry:
        return None
    path, expires_at = entry
    if expires_at <= time.time():
        _tokens.pop(token, None)
        return None
    try:
        return _safe_image_path(path)
    except (OSError, ValueError):
        _tokens.pop(token, None)
        return None


def provider_image_media_type(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"
