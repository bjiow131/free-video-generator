"""Find an installed local Blender without hard-coding a Blender release.

The explicit BLENDER_EXECUTABLE override is authoritative: an invalid override
fails closed instead of silently switching to another installation. No network
calls, package managers, registry writes, or automatic installation.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
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
