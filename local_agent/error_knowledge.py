"""Deterministic starter knowledge base for common local-agent failures.

This module diagnoses known patterns and recommends bounded next steps. It does
not execute fixes, run shell commands, or claim that a suggested fix is verified.
Unknown and high-risk failures must be escalated.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Pattern


@dataclass(frozen=True)
class ErrorRule:
    rule_id: str
    title: str
    patterns: tuple[Pattern[str], ...]
    category: str
    risk: str
    confidence: str
    diagnosis: str
    next_steps: tuple[str, ...]
    auto_fix_allowed: bool = False


_RULES: tuple[ErrorRule, ...] = (
    ErrorRule(
        "python-name-error", "Python name is undefined",
        (re.compile(r"\bNameError:\s*name .+ is not defined", re.I),),
        "python", "low", "medium",
        "A name is referenced but is not defined in the current scope.",
        ("Inspect the exact failing line and nearby scope.", "Check spelling, initialization order, and imports.", "Add or update a regression test before accepting a code change."),
    ),
    ErrorRule(
        "python-import-error", "Python import or dependency failed",
        (re.compile(r"\b(ModuleNotFoundError|ImportError):", re.I),),
        "python-dependency", "medium", "medium",
        "A module cannot be imported or a requested symbol is unavailable.",
        ("Check the active virtual environment and Python executable.", "Compare the import with requirements files and the installed package version.", "Do not install or upgrade packages automatically; request approval for dependency changes."),
    ),
    ErrorRule(
        "python-syntax-error", "Python syntax error",
        (re.compile(r"\bSyntaxError:", re.I),),
        "python", "low", "high",
        "Python could not parse a source file.",
        ("Use the traceback to identify the file and line.", "Inspect the changed lines and adjacent brackets, quotes, indentation, and commas.", "Run the narrow syntax check and relevant tests in an isolated worktree."),
    ),
    ErrorRule(
        "pytest-failure", "Automated tests failed",
        (re.compile(r"\b(FAILED|ERROR)\s+[^\n]+::|\bpytest\b.*\b(failed|error)", re.I),),
        "tests", "medium", "medium",
        "At least one automated test failed; the failure alone does not prove the code change is the cause.",
        ("Capture the complete failing assertion and traceback.", "Re-run only the failing test, then the relevant test group.", "Do not delete or weaken a failing test merely to obtain a green run."),
    ),
    ErrorRule(
        "git-conflict", "Git merge or patch conflict",
        (re.compile(r"\b(conflict \(content\)|CONFLICT \(|patch does not apply|git apply.*failed)\b", re.I),),
        "git", "medium", "medium",
        "The change does not apply cleanly to the selected base revision.",
        ("Preserve the current worktree and report its branch and base commit.", "Inspect the conflicting diff before attempting a resolution.", "Never run destructive reset/clean commands on a user worktree."),
    ),
    ErrorRule(
        "network-timeout", "Network request timed out",
        (re.compile(r"\b(TimeoutError|timed out|ReadTimeout|ConnectTimeout|connection reset)\b", re.I),),
        "network", "low", "medium",
        "A network operation did not complete; this may be transient or service-side.",
        ("Record the endpoint host, elapsed time, HTTP status if available, and request/correlation ID.", "Retry only bounded, idempotent operations with backoff.", "Do not log credentials, authorization headers, or full secret-bearing URLs."),
    ),
    ErrorRule(
        "http-auth-or-permission", "HTTP authentication or permission failure",
        (re.compile(r"\b(HTTP\s*401|HTTP\s*403|401 Unauthorized|403 Forbidden|Bad credentials|Resource not accessible by integration)\b", re.I),),
        "permissions", "high", "medium",
        "The request was rejected for authentication or authorization reasons.",
        ("Stop repeated retries and report the sanitized endpoint and operation.", "Ask the owner to verify token scope, expiry, and repository permissions.", "Never print, upload, or request the token itself in logs or reports."),
    ),
    ErrorRule(
        "http-rate-limit", "HTTP rate limit reached",
        (re.compile(r"\b(HTTP\s*429|rate limit exceeded|API rate limit)\b", re.I),),
        "network", "low", "medium",
        "The service is throttling requests.",
        ("Respect Retry-After or the service reset time.", "Use bounded exponential backoff and avoid tight polling loops.", "Do not rotate accounts or credentials to bypass limits."),
    ),
    ErrorRule(
        "invalid-image-size", "Unsupported image size",
        (re.compile(r"\b(invalid|unsupported|not allowed).{0,50}(image )?(size|resolution)|размер.{0,40}(изображения|картинки).{0,40}(недопустим|неподдерж)", re.I),),
        "request-validation", "low", "medium",
        "The requested image size may not be in the provider's supported set.",
        ("Read the provider's documented allowed values for the selected model.", "Validate the selected value before sending the request.", "Do not guess supported values or silently change the user's requested quality."),
    ),
    ErrorRule(
        "invalid-video-aspect-ratio", "Unsupported video aspect ratio",
        (re.compile(r"\b(supported|allowed).{0,50}(aspect.?ratio|9:16|16:9|1:1)|поддерживаются только\s+9:16", re.I),),
        "request-validation", "low", "medium",
        "The requested video aspect ratio may not be supported by the selected backend.",
        ("Use the selected backend's documented ratio allowlist.", "Validate the ratio separately on the video page before submitting.", "Do not reuse image settings for video settings."),
    ),
    ErrorRule(
        "unknown-or-unmatched", "No known error pattern matched",
        (re.compile(r"(?s).+"),),
        "unknown", "unknown", "low",
        "The error does not match a known deterministic rule; its cause is not established.",
        ("Save the full sanitized traceback/log and steps to reproduce.", "Record recent code changes, environment, and expected versus actual behavior.", "Do not apply speculative changes; escalate for review."),
    ),
)

HIGH_RISK_TERMS = re.compile(
    r"\b(delete|drop table|credential|token|secret|permission|access denied|data loss|database migration|production data)\b",
    re.I,
)


def diagnose_error(error_text: str) -> dict[str, object]:
    """Return a sanitized, deterministic diagnosis for an error/log excerpt."""
    if not isinstance(error_text, str) or not error_text.strip():
        error_text = ""
    bounded = error_text[:20_000]
    for rule in _RULES:
        if rule.rule_id == "unknown-or-unmatched":
            continue
        if any(pattern.search(bounded) for pattern in rule.patterns):
            high_risk_context = bool(HIGH_RISK_TERMS.search(bounded))
            return _result(rule, escalate=rule.risk == "high" or high_risk_context)
    rule = _RULES[-1]
    return _result(rule, escalate=True)


def _result(rule: ErrorRule, *, escalate: bool) -> dict[str, object]:
    return {
        "rule_id": rule.rule_id,
        "title": rule.title,
        "category": rule.category,
        "risk": rule.risk,
        "confidence": rule.confidence,
        "diagnosis": rule.diagnosis,
        "next_steps": list(rule.next_steps),
        "auto_fix_allowed": rule.auto_fix_allowed,
        "escalate": escalate,
        "note": "Diagnosis is a heuristic, not proof of root cause. Validate any change with tests.",
    }
