import ipaddress
import logging
import socket
from urllib.parse import urlsplit

import requests
from tenacity import retry, stop_after_attempt

logger = logging.getLogger(__name__)

_MAX_VIDEO_SIZE = 500 * 1024 * 1024


def _validate_download_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only HTTP(S) video URLs are allowed")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError("Video host could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("Video URL resolves to a non-public address")


@retry(stop=stop_after_attempt(3))
def download_video(url: str, save_path: str, max_size: int = _MAX_VIDEO_SIZE) -> None:
    _validate_download_url(url)
    logger.info("Downloading video to %s", save_path)
    resp = requests.get(url, timeout=(30, 300), stream=True)
    resp.raise_for_status()
    content_length = resp.headers.get("Content-Length")
    try:
        if content_length and int(content_length) > max_size:
            raise ValueError(f"Video too large: {content_length} bytes > max {max_size} bytes")
    except ValueError:
        if content_length and not content_length.isdigit():
            raise ValueError("Invalid video Content-Length")
        raise
    temporary = f"{save_path}.tmp"
    downloaded = 0
    try:
        with open(temporary, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > max_size:
                    raise ValueError(f"Video exceeded max_size {max_size} bytes during download")
                f.write(chunk)
        import os
        os.replace(temporary, save_path)
    finally:
        try:
            import os
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass
    logger.info("Video saved to %s (%s bytes)", save_path, downloaded)
