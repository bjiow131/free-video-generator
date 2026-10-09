"""Best-effort native Windows notification without third-party dependencies.

Notifications are sent only when an interactive Windows session is available.
A notification failure must never interrupt task execution or erase the local report.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
from typing import Any


def _powershell_executable() -> str | None:
    """Find a system PowerShell executable without accepting a remote path."""
    return shutil.which("powershell.exe") or shutil.which("powershell")


def notify_user(*, title: str, message: str) -> bool:
    """Show a short Windows notification; return False if unavailable.

    User-controlled text is embedded as Base64-encoded UTF-8 and decoded inside
    PowerShell, preventing quotes or punctuation from becoming executable syntax.
    """
    if os.name != "nt":
        return False
    executable = _powershell_executable()
    if not executable:
        return False

    title_b64 = base64.b64encode(title[:180].encode("utf-8")).decode("ascii")
    message_b64 = base64.b64encode(message[:700].encode("utf-8")).decode("ascii")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        f"$title=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{title_b64}')); "
        f"$message=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{message_b64}')); "
        "$n=New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon=[System.Drawing.SystemIcons]::Warning; "
        "$n.BalloonTipIcon=[System.Windows.Forms.ToolTipIcon]::Warning; "
        "$n.BalloonTipTitle=$title; $n.BalloonTipText=$message; $n.Visible=$true; "
        "$n.ShowBalloonTip(10000); Start-Sleep -Seconds 2; $n.Dispose()"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(
            [executable, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
             "-EncodedCommand", encoded],
            **kwargs,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
