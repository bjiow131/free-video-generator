"""Minimal, token-nonpersisting Telegram Bot API gateway for the owner's Render free service.

The local Windows Studio opts in explicitly before sending credentials to this
separate HTTPS gateway. It forwards a fixed allowlist of Bot API methods and bounded media bytes\nto Telegram's HTTPS hostname; it stores no bot tokens, messages, or images.
"""
from __future__ import annotations
import base64
import json
import os
import re
import uuid
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ALLOWED = {"getMe", "getUpdates", "sendMessage"}
BOT_TOKEN = re.compile(r"\d{5,15}:[A-Za-z0-9_-]{20,128}\Z")
MAX_BYTES = 4096
MAX_PHOTO = 9_500_000
MAX_VIDEO = 32_000_000
_MEDIA_LIMIT = 6
_MEDIA_RECENT: deque[float] = deque()
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
    if method == "getUpdates":
        # Pairing uses limit/timeout; the private supervisor additionally uses
        # an offset and a fixed allowed_updates=["message"] filter.
        fields = set(params)
        if (not {"limit", "timeout"} <= fields
                or not fields <= {"limit", "timeout", "offset", "allowed_updates"}
                or type(params["limit"]) is not int or not 1 <= params["limit"] <= 100
                or type(params["timeout"]) is not int or params["timeout"] != 0
                or ("offset" in params and (type(params["offset"]) is not int
                    or not 0 <= params["offset"] < 2**63))
                or ("allowed_updates" in params and params["allowed_updates"] != ["message"])):
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



def forward_media(token: str, chat: str, method: str,
                  caption_header: str, content: bytes) -> tuple[int, dict]:
    """Accept only byte uploads to one Telegram method and a numeric chat.

    No arbitrary URL/remote filename or shell execution; nothing is written
    to disk. This gateway is a transient forwarder, not a cloud media store.
    """
    if not isinstance(token, str) or not BOT_TOKEN.fullmatch(token):
        return 400, {"ok": False, "description": "Invalid bot token"}
    if method not in ("sendPhoto", "sendVideo"):
        return 400, {"ok": False, "description": "Unsupported media method"}
    if not isinstance(chat, str) or not re.fullmatch(r"[0-9]{1,20}", chat):
        return 400, {"ok": False, "description": "Invalid private chat"}
    if not isinstance(caption_header, str) or len(caption_header) > 1200:
        return 400, {"ok": False, "description": "Invalid caption"}
    try:
        caption = base64.b64decode(caption_header, altchars=b"-_", validate=True).decode("utf-8")
    except (ValueError, UnicodeError):
        return 400, {"ok": False, "description": "Invalid caption"}
    if len(caption) > 600:
        return 400, {"ok": False, "description": "Caption too long"}
    if not isinstance(content, bytes):
        return 400, {"ok": False, "description": "Invalid upload"}
    if method == "sendPhoto":
        if not 16 <= len(content) <= MAX_PHOTO:
            return 413, {"ok": False, "description": "Photo too large"}
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            suffix, mime = ".png", "image/png"
        elif content.startswith(b"\xff\xd8\xff"):
            suffix, mime = ".jpg", "image/jpeg"
        elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            suffix, mime = ".webp", "image/webp"
        else:
            return 415, {"ok": False, "description": "Invalid image signature"}
        field = "photo"
    else:
        if not 16 <= len(content) <= MAX_VIDEO:
            return 413, {"ok": False, "description": "Video too large"}
        if content[4:8] != b"ftyp":
            return 415, {"ok": False, "description": "Invalid MP4 signature"}
        suffix, mime, field = ".mp4", "video/mp4", "video"
    now = time.monotonic()
    with _MUTEX:
        while _MEDIA_RECENT and _MEDIA_RECENT[0] < now - WINDOW:
            _MEDIA_RECENT.popleft()
        if len(_MEDIA_RECENT) >= _MEDIA_LIMIT:
            return 429, {"ok": False, "description": "Media rate limited"}
        _MEDIA_RECENT.append(now)
    if not _limit():
        return 429, {"ok": False, "description": "Rate limited"}
    boundary = uuid.uuid4().hex
    mark = ("--" + boundary + "\r\n").encode("ascii")
    def form_field(name: str, value: str) -> bytes:
        return (mark + f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii")
                + value.encode("utf-8") + b"\r\n")
    upload = (form_field("chat_id", chat) + form_field("caption", caption)
              + mark + f'Content-Disposition: form-data; name="{field}"; filename="studio{suffix}"\r\n'.encode("ascii")
              + f"Content-Type: {mime}\r\n\r\n".encode("ascii")
              + content + b"\r\n" + ("--" + boundary + "--\r\n").encode("ascii"))
    # Mandatory Telegram Bot API URL contains the token; the relay never logs it.
    url = "https://api.telegram.org/bot" + token + "/" + method
    request = Request(url, method="POST", data=upload,
                      headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        with build_opener(RejectRedirect()).open(request, timeout=60) as response:
            raw = response.read(65537)
            code = response.status
    except HTTPError as exc:
        code = exc.code
        raw = exc.read(4097) if 400 <= code < 500 else b""
    except (URLError, TimeoutError, OSError):
        return 502, {"ok": False, "description": "Telegram media upstream unavailable"}
    if len(raw) > 65536:
        return 502, {"ok": False, "description": "Telegram response too large"}
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        return 502, {"ok": False, "description": "Telegram response not JSON"}
    if not isinstance(result, dict):
        return 502, {"ok": False, "description": "Telegram response invalid"}
    if code != 200:
        return (code if 400 <= code < 500 else 502), {
            "ok": False, "description": "Telegram returned HTTP " + str(code)}
    return 200, result


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
        if self.path == "/health/upstream":
            # No credentials, chat data or Telegram Bot API token used.
            if not _limit():
                return self._send(429, {"ok": False, "reason": "rate_limited"})
            url = "https://api.telegram.org/"
            try:
                request = Request(url, method="GET")
                with build_opener(RejectRedirect()).open(request, timeout=8):
                    return self._send(200, {"ok": True, "upstream": "reachable"})
            except HTTPError:
                # Telegram's root URL normally returns HTTP 4xx.
                return self._send(200, {"ok": True, "upstream": "reachable"})
            except (URLError, TimeoutError, OSError):
                return self._send(503, {"ok": False, "upstream": "unavailable"})
        self._send(404, {"ok": False})

    def do_POST(self):
        if self.path == "/api/telegram/media":
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/octet-stream":
                return self._send(415, {"ok": False})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 16 <= size <= MAX_VIDEO:
                    return self._send(413, {"ok": False})
                content = self.rfile.read(size)
                if len(content) != size:
                    return self._send(400, {"ok": False})
            except (OSError, ValueError):
                return self._send(400, {"ok": False})
            status, response = forward_media(
                self.headers.get("X-Telegram-Token", ""),
                self.headers.get("X-Telegram-Chat-Id", ""),
                self.headers.get("X-Telegram-Method", ""),
                self.headers.get("X-Telegram-Caption", ""), content)
            return self._send(status, response)
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
