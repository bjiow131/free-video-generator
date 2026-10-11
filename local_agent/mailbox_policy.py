"""Locally authorized unattended GitHub mailbox operations.

Opt-in is set through loopback Studio UI, NEVER from an incoming GitHub task.
An enabled policy auto-runs selected bounded handlers without the console YES.
Unreviewed patches, arbitrary commands and repairs are never auto-approved.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
POLICY_FILE = _ROOT / '.local_agent' / 'mailbox_policy.json'
_LOCK = threading.RLock()
_POLICY_FIELDS = {'enabled', 'allow_octava', 'allow_blender', 'allow_tests'}
READ_ONLY_OPERATIONS = frozenset({
    'doctor', 'preflight', 'status', 'blender_preflight',
    'blender_inspect_mia_project', 'blender_knowledge_search',
    'scan_project_assets', 'compile_story_plan',
})
BLENDER_OPERATIONS = frozenset({
    'save_story_plan', 'blender_forest_preview',
    'blender_mia_blockout', 'blender_mia_skeleton',
})
# Tests execute checked-out local project code. Require a separate checkbox.
TEST_OPERATIONS = frozenset({'test'})
# Never allow unattended: apply_patch, open GUI, start/stop, backup, logs,
# remotely provided code, unreviewed repair packages, or unknown operations.


class MailboxPolicyError(ValueError):
    pass


def default_policy() -> dict[str, bool]:
    return {'enabled': False, 'allow_octava': False, 'allow_blender': False,
            'allow_tests': False}


def _validate(data: Any) -> dict[str, bool]:
    if not isinstance(data, dict) or set(data) != _POLICY_FIELDS:
        raise MailboxPolicyError('Некорректные поля политики автономного режима')
    if any(type(data[name]) is not bool for name in _POLICY_FIELDS):
        raise MailboxPolicyError('Параметры автономного режима должны быть true/false')
    return {name: data[name] for name in ('enabled', 'allow_octava', 'allow_blender', 'allow_tests')}


def _safe_directory() -> Path:
    directory = POLICY_FILE.parent
    if directory.is_symlink() or getattr(directory, 'is_junction', lambda: False)():
        raise MailboxPolicyError('Папка политики не должна быть ссылкой или junction')
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve().is_relative_to(_ROOT.resolve()):
        raise MailboxPolicyError('Папка политики выходит за пределы приложения')
    return directory


def _safe_file(path: Path) -> None:
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
        raise MailboxPolicyError('Файл политики не должен быть ссылкой или junction')


def load_policy() -> dict[str, bool]:
    with _LOCK:
        _safe_directory()
        _safe_file(POLICY_FILE)
        try:
            blob = POLICY_FILE.read_bytes()
        except FileNotFoundError:
            return default_policy()
        except OSError as exc:
            raise MailboxPolicyError('Не удалось прочесть политику') from exc
        if len(blob) > 1024:
            raise MailboxPolicyError('Политика слишком большая')
        try:
            return _validate(json.loads(blob.decode('utf-8')))
        except (UnicodeError, ValueError, TypeError) as exc:
            raise MailboxPolicyError('Повреждена локальная политика; автономный режим заблокирован') from exc


def _atomic_write(path: Path, content: bytes) -> None:
    directory = _safe_directory()
    _safe_file(path)
    name = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.mailbox-policy-', suffix='.tmp',
                                         dir=directory, delete=False) as stream:
            name = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    except OSError as exc:
        raise MailboxPolicyError('Не удалось сохранить локальную политику') from exc
    finally:
        if name is not None:
            try:
                Path(name).unlink(missing_ok=True)
            except OSError:
                pass


def save_policy(value: dict[str, bool]) -> dict[str, bool]:
    data = _validate(value)
    with _LOCK:
        _atomic_write(POLICY_FILE, (json.dumps(data, sort_keys=True) + '\n').encode('utf-8'))
    return data


def is_auto_authorized(operation: str, policy: dict[str, bool] | None = None) -> bool:
    p = load_policy() if policy is None else _validate(policy)
    if not p['enabled']:
        return False
    if operation in READ_ONLY_OPERATIONS:
        return True
    if operation in BLENDER_OPERATIONS:
        return p['allow_blender']
    if operation in TEST_OPERATIONS:
        return p['allow_tests']
    if operation == 'octava_advice':
        return p['allow_octava']
    return False


def reserve_octava_call(now=None) -> None:
    """Backward-compatible no-op: no ChatGPT-side daily OctavAPI call limit.

    Authorization remains governed by the locally saved allow_octava policy.
    The third-party provider may independently charge for tokens or impose
    its own limits. Kept as a no-op for older poller/test integrations.
    """
    return None
