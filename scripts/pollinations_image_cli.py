#!/usr/bin/env python3
import os
import urllib.parse
import urllib.request

key = os.environ["POLLINATIONS_API_KEY"]
prompt = os.environ["IMAGE_PROMPT"]
model = os.environ.get("IMAGE_MODEL", "flux")
aspect = os.environ.get("IMAGE_ASPECT", "9:16")

url = "https://gen.pollinations.ai/image/" + urllib.parse.quote(prompt, safe="")
url += "?" + urllib.parse.urlencode({"model": model, "aspectRatio": aspect})

request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
try:
    with urllib.request.urlopen(request, timeout=300) as response:
        data = response.read()
except Exception as exc:
    raise SystemExit(f"Pollinations image request failed: {exc}")

if not data:
    raise SystemExit("Pollinations returned an empty image.")

with open("generated-image.jpg", "wb") as f:
    f.write(data)
print("Saved generated-image.jpg")
