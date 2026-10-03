#!/usr/bin/env python3
"""Generate an Agnes AI video from environment variables.

Required:
  AGNES_API_KEY
  VIDEO_PROMPT

Optional:
  VIDEO_SECONDS (4-12, default 10)
  VIDEO_ASPECT (default 9:16)
"""

import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error

BASE = "https://apihub.agnes-ai.com"

key = os.environ["AGNES_API_KEY"]
prompt = os.environ["VIDEO_PROMPT"]
seconds = int(os.environ.get("VIDEO_SECONDS", "10"))
aspect = os.environ.get("VIDEO_ASPECT", "9:16")

if not 4 <= seconds <= 12:
    raise SystemExit("VIDEO_SECONDS must be between 4 and 12.")

payload = {
    "model": "agnes-video-2.5-flash",
    "prompt": prompt,
    "mode": "text",
    "seconds": seconds,
    "size": "720P",
    "aspect_ratio": aspect,
    "n": 1,
}

headers = {
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
}

req = urllib.request.Request(
    f"{BASE}/v1/videos",
    data=json.dumps(payload).encode(),
    headers=headers,
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=120) as response:
        result = json.load(response)
except urllib.error.HTTPError as exc:
    raise SystemExit(
        f"Agnes API returned HTTP {exc.code}: "
        f"{exc.read().decode(errors='replace')[:2000]}"
    )

video_id = result.get("video_id") or result.get("task_id") or result.get("id")
if not video_id:
    raise SystemExit(f"No video id returned: {result}")

for _ in range(180):
    time.sleep(10)
    poll_url = (
        f"{BASE}/agnesapi?video_id={urllib.parse.quote(video_id)}"
        f"&model_name=agnes-video-2.5-flash"
    )
    poll = urllib.request.Request(
        poll_url,
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(poll, timeout=30) as response:
        status = json.load(response)

    state = str(status.get("status", "")).lower()
    print(f"status={state} progress={status.get('progress', 0)}%")

    if state == "completed":
        url = status.get("url") or status.get("video_url")
        if not url and isinstance(status.get("data"), dict):
            url = status["data"].get("url") or status["data"].get("video_url")
        if not url:
            raise SystemExit(f"Completed without video URL: {status}")
        urllib.request.urlretrieve(url, "agnes-video.mp4")
        print("Saved agnes-video.mp4")
        break

    if state == "failed":
        raise SystemExit(f"Agnes generation failed: {status.get('error', status)}")
else:
    raise SystemExit("Timed out waiting for Agnes video.")
