"""Real Agnes Image -> Video smoke test.

Run locally on Windows after setting AGNES_API_KEY. The key is read only
from the environment and is never printed or written to the repository.

Example:
    set AGNES_API_KEY=...
    python scripts/agnes_smoke_test.py

The test performs one image generation, one image-to-video submission, then
polls Agnes until the video completes and downloads the MP4.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.api.agnes_image import AgnesImageAPI
from core.api.agnes_video import AgnesVideoAPI


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(ROOT / "working" / "agnes_smoke"))
    parser.add_argument("--duration", type=int, default=5)
    args = parser.parse_args()

    api_key = os.environ.get("AGNES_API_KEY", "").strip()
    if not api_key:
        print("ERROR: AGNES_API_KEY is not set.")
        return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    image_path = out_dir / "smoke_image.png"
    video_path = out_dir / "smoke_video.mp4"

    image_api = AgnesImageAPI(api_key)
    print("1/4 Generating image with Agnes...")
    image = await image_api.generate_single_image(
        "A cinematic mountain landscape at sunrise, realistic photography, "
        "dramatic light, clean composition",
        size="1024x1024",
    )
    image.save(str(image_path))
    print(f"    OK: {image_path}")

    video_api = AgnesVideoAPI(api_key)
    print("2/4 Submitting Agnes image-to-video...")
    video_id = await video_api.submit_video(
        prompt=(
            "Animate the landscape naturally: slow forward camera movement, "
            "subtle moving clouds and atmospheric light, cinematic realism."
        ),
        reference_image_paths=[str(image_path)],
        duration=args.duration,
        width=1152,
        height=648,
    )
    print("    OK: video job submitted")

    def progress(status, progress, _):
        print(f"3/4 Poll: {status} {progress}%", flush=True)

    print("3/4 Polling Agnes until completion...")
    result = await video_api._poll_task(
        video_id,
        interval=60,
        max_poll_duration=1800,
        progress_callback=progress,
    )
    final_url = (
        result.get("url")
        or result.get("video_url")
        or (result.get("metadata") or {}).get("url")
    )
    if not final_url:
        raise RuntimeError(f"Completed Agnes task has no video URL: {result}")

    print("4/4 Downloading MP4...")
    from utils.video import download_video
    download_video(final_url, str(video_path))
    print(f"SUCCESS: {video_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
