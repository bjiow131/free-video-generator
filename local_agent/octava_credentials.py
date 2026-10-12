"""Rotate the optional OctavAPI key from the localhost Studio UI.

Only Windows Credential Manager persists keys. GitHub mailbox uses a different
credential target and remains independent of OctavAPI token balance.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TARGET = "LocalAgent/OctavAPI/api-key"
API_URL = "https://octavapi.shop/v1/chat/completions"
DEFAULT_MODEL = "gpt-6-luna"
SIMPLE_MODEL = "gpt-6-luna"
COMPLEX_MODEL = "gpt-6.1-sol"
MODEL_TIERS = frozenset({"default", "simple", "complex"})
MODEL_SETTINGS = Path(__file__).resolve().parents[1] / ".local_agent" / "octava_default_model.json"
_MODEL_LOCK = threading.RLock()
KEY_PATTERN = re.compile(r"[!-~]{12,2048}\Z", re.ASCII)
MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")


class OctavaKeyError(ValueError):
    """Safe user-facing error, never includes provider payloads or keys."""


def normalize_key(value: str) -> str:
    if not isinstance(value, str):
        raise OctavaKeyError("Введите API-ключ OctavAPI")
    key = value.strip()
    if not KEY_PATTERN.fullmatch(key):
        raise OctavaKeyError("Ключ должен содержать от 12 до 2048 символов без пробелов")
    return key


def configured_model() -> str:
    """Get the locally selected default; existing env setting works until changed."""
    path = MODEL_SETTINGS
    with _MODEL_LOCK:
        if (path.is_symlink() or getattr(path, "is_junction", lambda: False)()
                or path.parent.is_symlink()
                or getattr(path.parent, "is_junction", lambda: False)()):
            raise OctavaKeyError("Небезопасная конфигурация OctavAPI")
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            model = os.environ.get("OCTAVA_MODEL", DEFAULT_MODEL)
            if not MODEL_PATTERN.fullmatch(model):
                raise OctavaKeyError("Некорректная модель OctavAPI в настройках")
            return model
        except OSError:
            raise OctavaKeyError("Не удалось прочитать выбор модели") from None
        if len(raw) > 128:
            raise OctavaKeyError("Некорректный размер конфигурации модели")
        try:
            obj = json.loads(raw)
        except (ValueError, UnicodeError):
            raise OctavaKeyError("Некорректная конфигурация модели") from None
        if not isinstance(obj, dict) or set(obj) != {"model"} or obj["model"] not in (SIMPLE_MODEL, COMPLEX_MODEL):
            raise OctavaKeyError("Некорректная конфигурация модели")
        return obj["model"]


def set_default_model(data: dict, *, transport=None) -> dict:
    """Verify chosen model *before* atomically updating local default.

    One bounded billable probe is performed by explicit user action. No
    credentials are stored in this config and no existing key is replaced.
    """
    if not isinstance(data, dict) or set(data) != {"model"}:
        raise OctavaKeyError("Ожидается только поле model")
    model = data["model"]
    if type(model) is not str or model not in (SIMPLE_MODEL, COMPLEX_MODEL):
        raise OctavaKeyError("Модель OctavAPI не разрешена")
    key, source = read_key()
    if not key or source != "windows_vault":
        raise OctavaKeyError("Сначала сохраните ключ OctavAPI в Windows")
    if configured_model() == model:
        return key_status()
    probe_key(key, transport=transport, model=model)
    path = MODEL_SETTINGS
    with _MODEL_LOCK:
        if (path.is_symlink() or getattr(path, "is_junction", lambda: False)()
                or path.parent.is_symlink()
                or getattr(path.parent, "is_junction", lambda: False)()):
            raise OctavaKeyError("Небезопасная папка настроек модели")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".octava-model-", suffix=".tmp",
                mode="w", encoding="utf-8", delete=False,
            ) as output:
                temp = Path(output.name)
                json.dump({"model": model}, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, path)
        except OSError:
            raise OctavaKeyError("Не удалось сохранить модель OctavAPI") from None
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
    return key_status()


def model_for_tier(tier: str = "default") -> str:
    """Pick one known model per request; default retains legacy configuration.

    'complex' is not enabled by guesswork from free-form text; only a locally
    approved structured task may request the higher-cost model.
    """
    if not isinstance(tier, str) or tier not in MODEL_TIERS:
        raise OctavaKeyError("Недопустимая категория модели OctavAPI")
    if tier == "simple":
        return SIMPLE_MODEL
    if tier == "complex":
        return COMPLEX_MODEL
    return configured_model()


def read_key() -> tuple[str | None, str | None]:
    """Re-read vault for every request: new keys work without process restart."""
    if os.name == "nt":
        from local_agent.windows_credentials import CredentialStoreError, read_credential
        try:
            stored = read_credential(target=TARGET)
        except CredentialStoreError:
            raise OctavaKeyError("Не удалось открыть защищённое хранилище Windows") from None
        if stored:
            return stored, "windows_vault"
    fallback = os.environ.get("OCTAVA_API_KEY", "")
    return (fallback, "environment") if fallback else (None, None)


def key_status() -> dict:
    """Only readiness metadata; no key text, fingerprint, prefix, or suffix."""
    key, source = read_key()
    return {"configured": bool(key), "stored_locally": source == "windows_vault",
            "provider": "OctavAPI", "model": configured_model(),
            "simple_model": SIMPLE_MODEL, "complex_model": COMPLEX_MODEL,
            "github_connection_independent": True,
            "validation": "not_checked"}


def probe_key(key: str, *, transport=None, model: str | None = None) -> None:
    """A short *paid* live request verifies the candidate before vault replacement."""
    candidate = normalize_key(key)
    selected = configured_model() if model is None else model
    if type(selected) is not str or selected not in (SIMPLE_MODEL, COMPLEX_MODEL):
        raise OctavaKeyError("Неизвестная модель для проверки")
    payload = json.dumps({"model": selected,
                          "messages": [{"role": "user", "content": "Ответь ровно: OK"}],
                          "max_tokens": 12}, ensure_ascii=False).encode("utf-8")
    request = Request(API_URL, data=payload, method="POST",
                      headers={"Authorization": "Bearer " + candidate,
                               "Content-Type": "application/json"})
    try:
        sender = transport or urlopen
        with sender(request, timeout=18) as response:
            raw = response.read(65537)
    except HTTPError as exc:
        # Never include the provider response body or raw exception: either may
        # echo the bearer token or private request details. The numeric status
        # alone is sufficient for first-line diagnosis of Happ/proxy failures.
        code = exc.code if type(exc.code) is int and 400 <= exc.code <= 599 else None
        reasons = {
            400: "Сервер отклонил параметры запроса или модель",
            401: "Ключ OctavAPI не принят",
            402: "Недостаточно токенов на ключе OctavAPI",
            403: "Доступ отклонён (возможно, ограничение IP/VPN)",
            404: "Адрес API или выбранная модель не найдены",
            405: "Сервер не поддерживает метод запроса",
            407: "Прокси требует авторизацию — проверьте Happ",
            408: "Время ожидания запроса истекло",
            422: "Сервер отклонил параметры модели",
            429: "Превышен лимит запросов или баланс недоступен",
            451: "Доступ ограничен для текущего сетевого маршрута",
            500: "Ошибка сервера OctavAPI",
            502: "Шлюз или сервер модели недоступен",
            503: "Сервис OctavAPI временно недоступен",
            504: "Время ожидания вышестоящего сервера истекло",
        }
        if code is not None:
            raise OctavaKeyError(f"OctavAPI: HTTP {code} — {reasons.get(code, 'ошибка HTTP-сервера')}. Ключ не изменён") from None
        raise OctavaKeyError("OctavAPI: HTTP-ошибка без допустимого кода. Ключ не изменён") from None
    except (URLError, TimeoutError, OSError):
        raise OctavaKeyError("Не удалось подключиться к OctavAPI для проверки") from None
    if len(raw) > 65536:
        raise OctavaKeyError("Слишком большой ответ OctavAPI")
    try:
        data = json.loads(raw.decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty")
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError):
        raise OctavaKeyError("OctavAPI вернул непонятный ответ") from None


def store_key(key: str) -> None:
    from local_agent.windows_credentials import CredentialStoreError, write_credential
    try:
        write_credential(key, target=TARGET)
    except CredentialStoreError:
        raise OctavaKeyError("Не удалось сохранить ключ в защищённое хранилище Windows") from None


def replace_key(value: str, *, transport=None) -> dict:
    """Validate first, then atomically replace ONLY the OctavAPI credential.

    A failed candidate leaves the previously stored key intact.
    """
    candidate = normalize_key(value)
    if os.name != "nt":
        raise OctavaKeyError("Замена ключа через интерфейс поддерживается на Windows")
    probe_key(candidate, transport=transport)
    store_key(candidate)
    return {"configured": True, "stored_locally": True, "provider": "OctavAPI",
            "model": configured_model(), "validated": True,
            "github_connection_independent": True}