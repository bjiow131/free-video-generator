"""Find an installed local Blender without hard-coding a Blender release.

The explicit BLENDER_EXECUTABLE override is authoritative: an invalid override
fails closed instead of silently switching to another installation. No network
calls, package managers, registry writes, or automatic installation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
from typing import Callable, Mapping


def _installed_versions(environ: Mapping[str, str]) -> list[tuple[tuple[int, ...], Path]]:
    """Scan only conventional Blender installation directories on Windows."""
    found: list[tuple[tuple[int, ...], Path]] = []
    roots: set[Path] = set()
    for variable in ("PROGRAMFILES", "PROGRAMW6432", "PROGRAMFILES(X86)"):
        raw = environ.get(variable, "").strip()
        if raw:
            roots.add(Path(raw).expanduser())
    for root in roots:
        parent = root / "Blender Foundation"
        if not parent.is_dir():
            continue
        try:
            folders = parent.iterdir()
            for folder in folders:
                match = re.fullmatch(r"Blender (\d+)(?:\.(\d+))?(?:\.(\d+))?", folder.name)
                if not match:
                    continue
                candidate = folder / "blender.exe"
                if candidate.is_file():
                    found.append((
                        tuple(int(part) if part is not None else 0 for part in match.groups()),
                        candidate.resolve(),
                    ))
        except OSError:
            # An inaccessible installation directory is not executable.
            continue
    return found


def find_blender_executable(
    *,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
    windows: bool | None = None,
) -> Path | None:
    """Resolve an explicit override, installed Windows version, then PATH."""
    env = os.environ if environ is None else environ
    configured = env.get("BLENDER_EXECUTABLE", "").strip()
    if configured:
        path = Path(configured).expanduser()
        # A user-provided path must never silently fall back to some other exe.
        return path.resolve() if path.is_file() else None
    if windows is None:
        windows = os.name == "nt"
    if windows:
        versions = _installed_versions(env)
        if versions:
            versions.sort(key=lambda item: item[0], reverse=True)
            return versions[0][1]
    locate = shutil.which if which is None else which
    for name in ("blender.exe", "blender"):
        path_str = locate(name)
        if path_str:
            path = Path(path_str).expanduser()
            if path.is_file():
                return path.resolve()
    return None


_SUPPORTED_WINDOWS_MACHINES = {0x8664, 0xAA64}  # AMD64 and ARM64


def is_supported_windows_blender(path: str | os.PathLike[str]) -> bool:
    """Check the PE header before asking Windows to launch a Blender binary."""
    try:
        with Path(path).open("rb") as stream:
            dos = stream.read(64)
            if len(dos) < 64 or dos[:2] != b"MZ":
                return False
            offset = int.from_bytes(dos[0x3C:0x40], "little")
            if offset < 64 or offset > 1_048_576:
                return False
            stream.seek(offset)
            header = stream.read(6)
        return (len(header) == 6 and header[:4] == bytes((80, 69, 0, 0))
                and int.from_bytes(header[4:6], "little") in _SUPPORTED_WINDOWS_MACHINES)
    except (OSError, ValueError):
        return False


def _matches_unsupported_16bit_dialog(title: str, body: str, executable: str | os.PathLike[str]) -> bool:
    """Match only the known Windows loader dialog for the Blender process we launched."""
    normalized_title = " ".join(title.casefold().split())
    known_titles = {
        "unsupported 16-bit application",
        "unsupported 16 bit application",
        "неподдерживаемое 16-разрядное приложение",
        "неподдерживаемое 16 разрядное приложение",
    }
    if normalized_title not in known_titles:
        return False
    slash = chr(92)
    normalized_body = body.casefold().replace("/", slash)
    requested = str(Path(executable)).casefold().replace("/", slash)
    basename = Path(executable).name.casefold()
    if requested not in normalized_body and basename not in normalized_body:
        return False
    return any(marker in normalized_body for marker in (
        "64-bit", "64 bit", "64-разряд", "64 разряд",
    ))


def _dismiss_matching_dialogs(executable: str, events: list[dict[str, object]]) -> None:
    """Close only the exact compatibility dialog referring to our Blender executable."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    wm_close = 0x0010
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def window_text(hwnd) -> str:
        length = min(int(user32.GetWindowTextLengthW(hwnd)), 4096)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def visit(hwnd, _lparam):
        title = window_text(hwnd)
        if not title:
            return True
        child_text = []

        def visit_child(child, _child_param):
            value = window_text(child)
            if value:
                child_text.append(value)
            return True

        child_callback = enum_proc_type(visit_child)
        user32.EnumChildWindows(hwnd, child_callback, 0)
        body = " ".join(child_text)
        if _matches_unsupported_16bit_dialog(title, body, executable):
            if user32.PostMessageW(hwnd, wm_close, 0, 0):
                events.append({"code": "unsupported_16bit_blender_dialog", "closed": True})
        return True

    callback = enum_proc_type(visit)
    user32.EnumWindows(callback, 0)


@contextmanager
def watch_unsupported_blender_dialogs(executable: str | os.PathLike[str], events: list[dict[str, object]]):
    """Auto-close one known Windows compatibility popup while a Blender launch is active."""
    if os.name != "nt":
        yield events
        return
    stopped = threading.Event()
    resolved = str(Path(executable).resolve())

    def watch() -> None:
        while not stopped.is_set():
            try:
                _dismiss_matching_dialogs(resolved, events)
            except (OSError, AttributeError):
                pass
            stopped.wait(0.25)

    thread = threading.Thread(target=watch, name="blender-dialog-guard", daemon=True)
    thread.start()
    try:
        yield events
    finally:
        stopped.set()
        thread.join(timeout=1.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the locally installed Blender executable")
    parser.add_argument("--check", action="store_true", help="Check Blender --version without launching its GUI")
    args = parser.parse_args(argv)
    found = find_blender_executable()
    if found is None:
        print(
            "Blender was not found. Install Blender, add blender.exe to PATH, "
            "or set BLENDER_EXECUTABLE to its full local path.",
            file=sys.stderr,
        )
        return 2
    if args.check:
        if os.name == "nt" and not is_supported_windows_blender(found):
            print("Configured Blender is not a supported 64-bit Windows executable.", file=sys.stderr)
            return 2
        try:
            result = subprocess.run(
                [str(found), "--version"], capture_output=True, text=True,
                timeout=15, shell=False, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"Blender validation failed: {type(exc).__name__}", file=sys.stderr)
            return 2
        if result.returncode != 0:
            print("Blender --version returned an error.", file=sys.stderr)
            return 2
        lines = (result.stdout or result.stderr).splitlines()
        version = lines[0][:160] if lines else "version unavailable"
        print(f"Blender available: {version}")
    else:
        print(str(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
