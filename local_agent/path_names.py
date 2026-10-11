"""Portable Windows filename rules for identifiers used as local paths."""
from __future__ import annotations

import re

_DEVICE = r"(?!(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$))"


def path_identifier_pattern(max_length: int, *, dots: bool = False) -> re.Pattern[str]:
    """Build the existing ASCII allowlist with Windows device names excluded."""
    characters = r"A-Za-z0-9._-" if dots else r"A-Za-z0-9_-"
    return re.compile(r"^" + _DEVICE + r"[A-Za-z0-9][" + characters + r"]{0," + str(max_length - 1) + r"}$")


def is_windows_device_name(name: str) -> bool:
    """Extensions do not make Windows device basenames safe."""
    return bool(re.match(r"^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", name, re.I))


def is_link_or_junction(path) -> bool:
    """Reject Windows reparse points on Python 3.11 as well as ordinary symlinks."""
    import stat
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
