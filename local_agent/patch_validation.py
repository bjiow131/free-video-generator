"""Strict, standard-library-only validation of remotely supplied Git patch paths.

This is a path and patch-format gate, NOT a sandbox. Approved Python changes
may execute during the subsequent test run and must be reviewed locally.
"""
from __future__ import annotations

import re


class PatchValidationError(ValueError):
    """A patch has an unsafe path, file mode, or unsupported Git metadata."""


_ALLOWED_PREFIXES = ("local_agent/", "tests/", "docs/", "scripts/")
_ALLOWED_ROOT_FILES = frozenset({"README.md", "requirements-github-mailbox.txt"})
_UNSAFE_METADATA = ("rename from ", "rename to ", "copy from ", "copy to ")
_RESERVED_WINDOWS = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


def _path(path: str) -> str:
    if not path or any(c in path for c in "\\:*?\"<>|\t "):
        raise PatchValidationError("patch contains an unsafe path")
    if path.startswith("/") or not (path.startswith(_ALLOWED_PREFIXES) or path in _ALLOWED_ROOT_FILES):
        raise PatchValidationError("patch path is outside the repair allowlist")
    segments = path.split("/")
    if any(
        not part or part in (".", "..") or part.endswith(".")
        or part.casefold().startswith(".git") or _RESERVED_WINDOWS.match(part)
        for part in segments
    ):
        raise PatchValidationError("patch contains an unsafe path")
    return path


def validate_patch_paths(patch: str) -> None:
    """Reject unsupported diff metadata and ensure EVERY file header names one safe path.

    Only plain same-path Git changes, additions, and deletions are supported.
    Renames, copies, special modes, quoted path syntax and binary diffs are
    deliberately rejected rather than interpreted differently by Git.
    """
    if not isinstance(patch, str) or not patch.startswith("diff --git "):
        raise PatchValidationError("patch has no git diff headers")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in patch) or "\x7f" in patch:
        raise PatchValidationError("patch contains terminal control characters")

    expected = None
    old_header = new_header = False
    in_hunk = False
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if (len(parts) != 4 or not parts[2].startswith("a/")
                    or not parts[3].startswith("b/")):
                raise PatchValidationError("malformed git diff header")
            old = _path(parts[2][2:])
            new = _path(parts[3][2:])
            if old != new:
                raise PatchValidationError("renames and copies are not supported")
            expected = old
            old_header = new_header = in_hunk = False
            continue
        if expected is None:
            raise PatchValidationError("patch has no git diff headers")
        if line.startswith(("GIT binary patch", "Binary files ")):
            raise PatchValidationError("binary patches are prohibited")
        if in_hunk:
            # Patch body content is not metadata. Git apply checks hunk syntax.
            continue
        if line.startswith(_UNSAFE_METADATA):
            raise PatchValidationError("renames and copies are not supported")
        if line.startswith(("old mode ", "new mode ")):
            raise PatchValidationError("file mode changes are prohibited")
        if line.startswith(("new file mode ", "deleted file mode ")):
            if line not in ("new file mode 100644", "deleted file mode 100644"):
                raise PatchValidationError("special or executable file modes are prohibited")
        if line.startswith("--- "):
            if line[4:] not in (f"a/{expected}", "/dev/null"):
                raise PatchValidationError("unified header does not match diff path")
            old_header = True
        elif line.startswith("+++ "):
            if line[4:] not in (f"b/{expected}", "/dev/null"):
                raise PatchValidationError("unified header does not match diff path")
            new_header = True
        elif line.startswith("@@ "):
            if not old_header or not new_header:
                raise PatchValidationError("patch hunk has incomplete file headers")
            in_hunk = True
