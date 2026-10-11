"""Minimal, token-nonpersisting Telegram Bot API gateway for the owner's Render free service.

The local Windows Studio opts in explicitly before sending credentials to this
separate HTTPS gateway. It forwards only getMe/getUpdates/sendMessage, to the
fixed Telegram Bot API hostname; it stores no bot tokens or messages.
"""
from __future__ import annotations
import json
import os
import re
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ALLOWED = {"getMe", "getUpdates", "sendMessage"}
BOT_TOKEN = re.compile(r"\d{5,15}:[A-Za-z0-9_-]{20,128}\Z")
MAX_BYTES = 4096
WINDOW = 60
RATE_LIMIT = 24
_MUTEX = threading.RLock()
_RECENT: deque[float] = deque()


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _limit() -> bool:
    now = time.monotonic()
    with _MUTEX:
        while _RECENT and _RECENT[0] < now - WINDOW:
            _RECENT.popleft()
        if len(_RECENT) >= RATE_LIMIT:
            return False
        _RECENT.append(now)
        return True


def forward(data: dict) -> tuple[int, dict]:
    if not isinstance(data, dict) or set(data) != {"token", "method", "params"}:
        return 400, {"ok": False, "description": "Invalid request"}
    token, method, params = data["token"], data["method"], data["params"]
    if not isinstance(token, str) or not BOT_TOKEN.fullmatch(token):
        return 400, {"ok": False, "description": "Invalid token format"}
    if method not in ALLOWED or not isinstance(params, dict):
        return 400, {"ok": False, "description": "Unsupported method"}
    if method == "getMe" and params:
        return 400, {"ok": False, "description": "Unexpected parameters"}
    if method == "getUpdates" and (set(params) != {"limit", "timeout"}
                                   or type(params["limit"]) is not int
                                   or type(params["timeout"]) is not int
                                   or not 1 <= params["limit"] <= 100
                                   or params["timeout"] != 0):
        return 400, {"ok": False, "description": "Invalid polling parameters"}
    if method == "sendMessage":
        if set(params) != {"chat_id", "text"}:
            return 400, {"ok": False, "description": "Invalid message fields"}
        chat, message = params["chat_id"], params["text"]
        if not isinstance(chat, (str, int)) or not re.fullmatch(r"-?\d{1,20}", str(chat)):
            return 400, {"ok": False, "description": "Invalid chat"}
        if not isinstance(message, str) or not 1 <= len(message) <= 800:
            return 400, {"ok": False, "description": "Invalid message"}
    if not _limit():
        return 429, {"ok": False, "description": "Rate limited"}
    encoded = json.dumps(params, ensure_ascii=False).encode("utf-8")
    # An attacker cannot select arbitrary hosts or URLs. Tokens occur only in
    # Telegram's mandatory HTTPS path; never logged by this relay.
    url = "https://api.telegram.org/bot" + token + "/" + method
    request = Request(url, method="POST", data=encoded,
                      headers={"Content-Type": "application/json"})
    opener = build_opener(RejectRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(65537)
            code = response.status
    except HTTPError as exc:
        code = exc.code
        raw = exc.read(4097) if 400 <= code < 500 else b""
    except (URLError, TimeoutError, OSError):
        return 502, {"ok": False, "description": "Telegram upstream unavailable"}
    if len(raw) > 65536:
        return 502, {"ok": False, "description": "Telegram response too large"}
    try:
        out = json.loads(raw)
    except (ValueError, UnicodeError):
        return 502, {"ok": False, "description": "Telegram response not JSON"}
    if not isinstance(out, dict):
        return 502, {"ok": False, "description": "Telegram response invalid"}
    if code != 200:
        return code if 400 <= code < 500 else 502, {
            "ok": False, "description": "Telegram returned HTTP " + str(code)}
    return 200, out


class Handler(BaseHTTPRequestHandler):
    server_version = "OctavaTelegramBridge"
    sys_version = ""

    def log_message(self, format, *args):
        # Request bodies, Telegram tokens and addresses never enter logs.
        return

    def _send(self, status: int, body: dict) -> None:
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True, "service": "telegram-relay"})
        self._send(404, {"ok": False})

    def do_POST(self):
        if self.path != "/api/telegram":
            return self._send(404, {"ok": False})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._send(415, {"ok": False})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BYTES:
                return self._send(413, {"ok": False})
            raw = self.rfile.read(size)
            body = json.loads(raw)
        except (ValueError, UnicodeError, OSError):
            return self._send(400, {"ok": False})
        status, response = forward(body)
        self._send(status, response)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    if not 1024 <= port <= 65535:
        raise SystemExit("Invalid port")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever(poll_interval=0.5)
