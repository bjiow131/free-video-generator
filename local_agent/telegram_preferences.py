"""User-controlled Telegram alert preference, shared by Studio and mailbox worker.

This opt-in/out setting is local-only, contains no chat IDs or bot tokens,
and is deliberately separate from Telegram's connection/transport settings.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFERENCE_PATH = ROOT / ".local_agent" / "telegram_notifications.json"
_LOCK = threading.RLock()


class TelegramPreferenceError(ValueError):
    pass


def _safe_path() -> Path:
    path = PREFERENCE_PATH
    if (path.parent.is_symlink()
            or getattr(path.parent, "is_junction", lambda: False)()
            or path.is_symlink()
            or getattr(path, "is_junction", lambda: False)()):
        raise TelegramPreferenceError("Недопустимый путь настроек уведомлений")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.parent.resolve().is_relative_to(ROOT.resolve()):
        raise TelegramPreferenceError("Настройки должны храниться внутри приложения")
    return path


def _validate(value: object) -> dict[str, bool]:
    if (not isinstance(value, dict) or set(value) != {"enabled"}
            or type(value["enabled"]) is not bool):
        raise TelegramPreferenceError("Ожидается только enabled: true/false")
    return {"enabled": value["enabled"]}


def load_notifications() -> dict[str, bool]:
    """Preserve existing configured Telegram alerts after upgrading."""
    with _LOCK:
        path = _safe_path()
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return {"enabled": True}
        except OSError as exc:
            raise TelegramPreferenceError("Не удалось прочитать настройки уведомлений") from exc
        if len(raw) > 128:
            raise TelegramPreferenceError("Некорректные настройки уведомлений")
        try:
            return _validate(json.loads(raw.decode("utf-8")))
        except (UnicodeError, ValueError, TypeError) as exc:
            raise TelegramPreferenceError("Повреждены настройки уведомлений") from exc


def save_notifications(value: dict) -> dict[str, bool]:
    checked = _validate(value)
    with _LOCK:
        path = _safe_path()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=".telegram-notifications-", suffix=".tmp", delete=False,
            ) as output:
                temporary = Path(output.name)
                json.dump(checked, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            raise TelegramPreferenceError("Не удалось сохранить настройки уведомлений") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return checked


def notifications_enabled() -> bool:
    """Fail closed if preferences are unreadable or tampered with."""
    try:
        return load_notifications()["enabled"]
    except (TelegramPreferenceError, OSError):
        return False
