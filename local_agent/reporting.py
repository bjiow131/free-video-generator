"""Local diagnostic report writing with conservative secret redaction."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os
import re

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)(\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*"),
)
_HOME = str(Path.home())


def redact_text(value: str) -> str:
    """Redact common credential formats and the current user's home path."""
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(lambda m: (m.group(1) + m.group(2) + "[REDACTED]") if m.lastindex and m.lastindex >= 2 else "[REDACTED]", result)
    if _HOME and len(_HOME) > 3:
        result = result.replace(_HOME, "[USER_HOME]")
    return result


def write_report(report_dir: str | Path, *, kind: str, status: str,
                 details: dict[str, Any] | None = None) -> Path:
    """Write a timestamped JSON report locally; never uploads it."""
    root = Path(report_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_kind = re.sub(r"[^a-zA-Z0-9_-]", "_", kind)[:40] or "report"
    target = root / f"{stamp}_{safe_kind}.json"
    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "kind": safe_kind,
        "status": status,
        "computer_name_included": False,
        "details": _redact_value(details or {}),
    }
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(target)
    return target


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(k): _redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(v) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))
