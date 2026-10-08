"""Lightweight timing instrumentation for pipeline baseline profiling.

Instrumentation only: it does not alter return values or control flow.
"""
from __future__ import annotations

import contextvars
import functools
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class _TimingFrame:
    step: str
    started: float
    child_seconds: float = 0.0


_stack: contextvars.ContextVar[tuple[_TimingFrame, ...]] = contextvars.ContextVar(
    "timing_stack", default=()
)
_records: contextvars.ContextVar[list[tuple[str, float, float]]] = contextvars.ContextVar(
    "timing_records", default=[]
)


def _enter(step: str) -> None:
    stack = _stack.get()
    records = _records.get()
    if not stack:
        records = []
        _records.set(records)
    _stack.set(stack + (_TimingFrame(step=step, started=time.perf_counter()),))


def _exit() -> None:
    stack = _stack.get()
    if not stack:
        return
    frame = stack[-1]
    elapsed = time.perf_counter() - frame.started
    exclusive = max(0.0, elapsed - frame.child_seconds)
    _records.get().append((frame.step, elapsed, exclusive))
    print(f"[Timing] step={frame.step} sec={elapsed:.4f}", flush=True)
    parent_stack = stack[:-1]
    if parent_stack:
        parent = parent_stack[-1]
        parent.child_seconds += elapsed
        _stack.set(parent_stack)
    else:
        _stack.set(())
        records = _records.get()
        total = max((item[1] for item in records), default=0.0)
        if records and total > 0:
            print("[Timing] summary", flush=True)
            print("[Timing] step | sec | % of total", flush=True)
            for step, elapsed_value, exclusive in sorted(
                records, key=lambda item: item[2], reverse=True
            ):
                pct = exclusive / total * 100.0
                print(f"[Timing] {step} | {exclusive:.4f} | {pct:.1f}%", flush=True)
            print(f"[Timing] total | {total:.4f} | 100.0%", flush=True)
        _records.set([])


def timed_step(func: Callable[..., Any]) -> Callable[..., Any]:
    """Measure a sync or async function with perf_counter()."""
    step = f"{func.__module__}.{func.__qualname__}"

    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            _enter(step)
            try:
                return await func(*args, **kwargs)
            finally:
                _exit()
        return async_wrapper

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        _enter(step)
        try:
            return func(*args, **kwargs)
        finally:
            _exit()

    return wrapper
