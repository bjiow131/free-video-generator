"""Explicitly opt-in, bounded OctavAPI *advice*, not a remote execution agent.

This module never calls Blender, Python eval, Git, or the shell. It passes one
short, user-approved text question to a third-party provider. The original
ChatGPT session is not accessible through this API.
"""
from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://octavapi.shop/v1/chat/completions"
MAX_INPUT = 1600
MAX_OUTPUT = 2500
MAX_RESPONSE_BYTES = 65536
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
_SECRET = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{16,}|github_pat_[A-Za-z0-9_]{12,}|gh[pousr]_[A-Za-z0-9]{12,}"
    r"|(?:api[_-]?key|token|пароль|password|authorization)\s*[:=]\s*\S+)"
)


class OctavaAdviceError(ValueError):
    """Safe error class; messages never contain provider payloads or credentials."""


def validate_prompt(prompt: str) -> str:
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= MAX_INPUT:
        raise OctavaAdviceError("Question must contain 1-1600 characters")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in prompt):
        raise OctavaAdviceError("Question contains forbidden control characters")
    if _SECRET.search(prompt):
        raise OctavaAdviceError("Question appears to contain a secret or credential")
    return prompt.strip()


def request_advice(prompt: str, *, transport=None) -> dict:
    """Request up to 320 tokens; requires explicit local opt-in and local key.

    Result is explanatory text only, never automatically parsed as a command.
    The transport hook is for deterministic offline tests.
    """
    question = validate_prompt(prompt)
    # Re-read the Windows vault on EACH request, including in a long-running
    # GitHub poller process. A locally saved key is explicit user opt-in.
    # Legacy environment-only use retains its explicit opt-in flag.
    from local_agent.octava_credentials import OctavaKeyError, read_key
    try:
        key, source = read_key()
    except OctavaKeyError:
        raise OctavaAdviceError("OctavAPI credential storage is unavailable") from None
    if source != "windows_vault" and os.environ.get("LOCAL_AGENT_ALLOW_OCTAVA") != "1":
        raise OctavaAdviceError("OctavAPI calls are disabled until LOCAL_AGENT_ALLOW_OCTAVA=1")
    if not key or key != key.strip() or any(c in key for c in "\n\r"):
        raise OctavaAdviceError("OCTAVA_API_KEY is missing or malformed")
    model = os.environ.get("OCTAVA_MODEL", "gpt-6-luna")
    if not _MODEL.fullmatch(model):
        raise OctavaAdviceError("Invalid configured model ID")
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "You give concise Blender scene planning advice in Russian. "
             "This is a text-only advisory. Never ask for API keys or suggest executing shell code. "
             "Do not pretend any Blender scene was rendered."},
            {"role": "user", "content": question},
        ],
        "max_tokens": 320,
    }, ensure_ascii=False).encode("utf-8")
    req = Request(
        BASE_URL, data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    sender = transport or urlopen
    try:
        with sender(req, timeout=25) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise OctavaAdviceError("OctavAPI authorization failed") from None
        if exc.code == 402:
            raise OctavaAdviceError("OctavAPI reported insufficient balance") from None
        if exc.code == 429:
            raise OctavaAdviceError("OctavAPI rate limit reached") from None
        raise OctavaAdviceError("OctavAPI returned HTTP error") from None
    except (URLError, OSError, TimeoutError):
        raise OctavaAdviceError("OctavAPI request failed or timed out") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise OctavaAdviceError("OctavAPI response exceeded limit")
    try:
        data = json.loads(raw.decode("utf-8"))
        text = data["choices"][0]["message"]["content"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("invalid response")
        # The result is inert text. Any commands embedded in it are never run.
        answer = text.strip()[:MAX_OUTPUT]
        usage = data.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        safe_usage = {k: v for k, v in usage.items()
                      if k in ("prompt_tokens", "completion_tokens", "total_tokens")
                      and type(v) is int and 0 <= v <= 1_000_000}
        return {"status": "completed", "advice": answer, "model_requested": model,
                "usage": safe_usage, "executed_anything": False,
                "provider": "OctavAPI (third-party)",
                "note": "Suggestion only; no Blender command or patch has been executed."}
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError):
        raise OctavaAdviceError("Unexpected OctavAPI response format") from None