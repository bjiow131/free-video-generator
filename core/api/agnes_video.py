"""Agnes Video API client.

Supports the current Agnes Video 2.5 protocol and the legacy v2.0 protocol.
The public API remains compatible with the existing pipelines.
"""
from core.timing import timed_step


import asyncio
import base64
import json
import logging
import mimetypes
import os
import time
from typing import List, Optional, Sequence

import requests

from core.api.rate_limiter import get_rate_limiter
from utils.video import download_video

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1").rstrip("/")
API_ROOT = BASE_URL.rsplit("/v1", 1)[0] if "/v1" in BASE_URL else "https://apihub.agnes-ai.com"

DEFAULT_MODEL = os.environ.get("AGNES_VIDEO_MODEL", "agnes-video-2.5-flash")
LEGACY_MODEL = "agnes-video-v2.0"
MODERN_MODELS = frozenset({"agnes-video-2.5-flash", "agnes-video-2.5"})

DURATION_PRESETS = {
    5: (121, 24),
    10: (241, 24),
    15: (361, 24),
    18: (409, 24),
    20: (409, 24),
}


class VideoOutput:
    def __init__(self, fmt: str, ext: str, data):
        self.fmt = fmt
        self.ext = ext
        self.data = data

    def save(self, path: str) -> None:
        """Write the video atomically so interrupted downloads never look complete."""
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        tmp_path = path + ".tmp"
        try:
            if self.fmt == "url":
                download_video(self.data, tmp_path)
            else:
                with open(tmp_path, "wb") as f:
                    f.write(self.data if isinstance(self.data, bytes) else self.data.encode())
                    f.flush()
                    os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise


class AgnesVideoAPI:
    """Agnes Video generation client (t2v / i2v / keyframes)."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        default_duration: int = 5,
        max_retries: int = 5,
        retry_base_delay: float = 30.0,
    ):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.default_duration = default_duration
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.shutdown_event = None
        self._poll_api = self
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @property
    def is_modern(self) -> bool:
        return self.model in MODERN_MODELS

    async def _path_to_b64(self, path: str) -> str:
        def _read() -> str:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        b64 = await asyncio.to_thread(_read)
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{b64}"

    async def _resolve_image_ref(self, ref: str) -> str:
        """Resolve local files to data URIs; modern Agnes accepts these directly."""
        if ref.startswith(("http://", "https://", "data:")):
            return ref
        if os.path.exists(ref):
            return await self._path_to_b64(ref)
        return ref

    def _aspect_ratio(self, width: int, height: int) -> str:
        ratio = width / max(height, 1)
        candidates = {
            "16:9": 16 / 9,
            "9:16": 9 / 16,
            "1:1": 1.0,
            "4:3": 4 / 3,
            "3:4": 3 / 4,
            "21:9": 21 / 9,
        }
        return min(candidates, key=lambda key: abs(candidates[key] - ratio))

    def _modern_seconds(self, duration: Optional[int]) -> int:
        requested = int(duration or self.default_duration)
        # Agnes Video 2.5 accepts 4..12 seconds.
        return max(4, min(12, requested))

    def _get_max_frames(self, width: int, height: int) -> int:
        pixels = width * height
        if pixels > 1280 * 720:
            return 169
        if pixels > 854 * 480:
            return 409
        return 961

    def _get_frame_config(self, duration: Optional[int] = None,
                          width: int = 1152, height: int = 648) -> tuple:
        d = duration or self.default_duration
        max_nf = self._get_max_frames(width, height)
        if d in DURATION_PRESETS:
            nf, fr = DURATION_PRESETS[d]
            return (nf, fr) if nf <= max_nf else (max_nf, fr)
        best = None
        for nf in range(9, min(410, max_nf + 1), 8):
            fr = round(nf / d)
            if 1 <= fr <= 60:
                best = (nf, fr)
        return best or DURATION_PRESETS[5]

    @timed_step
    async def _poll_task(
        self,
        video_id: str,
        interval: int = 5,
        max_poll_duration: int = 1800,
        max_consecutive_failures: int = 10,
        progress_callback=None,
    ) -> dict:
        last_status = ""
        poll_count = 0
        consecutive_failures = 0
        start_time = asyncio.get_event_loop().time()

        while True:
            if self.shutdown_event and self.shutdown_event.is_set():
                raise RuntimeError("Video generation cancelled by user")

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > max_poll_duration:
                raise RuntimeError(
                    f"[AgnesVideo] Polling timed out after {max_poll_duration}s "
                    f"for video {video_id[:16]}"
                )

            try:
                await asyncio.to_thread(get_rate_limiter().acquire)
                # Agnes recommends querying legacy v2.0 jobs by video_id alone.
                # Passing model_name is only necessary for non-default/upstream IDs;
                # omitting it avoids the legacy endpoint getting pinned to a stale model route.
                params = {"video_id": video_id}
                if self.is_modern:
                    params["model_name"] = self.model
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        requests.get,
                        f"{API_ROOT}/agnesapi",
                        headers=self.headers,
                        params=params,
                        timeout=15,
                    ),
                    timeout=30,
                )
                resp.raise_for_status()
                result = resp.json()
                status = str(result.get("status", "")).lower()
                progress = result.get("progress", 0)
                poll_count += 1
                consecutive_failures = 0

                if status != last_status:
                    logger.info(
                        "[AgnesVideo] %s model=%s status=%s progress=%s%% poll=%d",
                        video_id[:16], self.model, status, progress, poll_count,
                    )
                    last_status = status
                else:
                    logger.info(
                        "[AgnesVideo] %s model=%s heartbeat status=%s progress=%s%% poll=%d",
                        video_id[:16], self.model, status, progress, poll_count,
                    )

                if progress_callback:
                    progress_callback(
                        status,
                        progress,
                        f"Agnes {self.model}: {status or 'processing'} · {progress}%"
                    )

                if status == "completed":
                    return result
                if status == "failed":
                    raise RuntimeError(
                        f"Video generation failed: {result.get('error') or 'unknown error'}"
                    )
            except (requests.exceptions.RequestException, asyncio.TimeoutError) as exc:
                consecutive_failures += 1
                logger.warning(
                    "[AgnesVideo] Poll error (%d/%d): %s",
                    consecutive_failures, max_consecutive_failures, exc,
                )
                if consecutive_failures >= max_consecutive_failures:
                    raise RuntimeError(
                        f"[AgnesVideo] Polling failed after "
                        f"{max_consecutive_failures} consecutive errors for {video_id[:16]}"
                    )
            finally:
                try:
                    resp.close()
                except (NameError, AttributeError):
                    pass

            # Poll frequently enough for responsive UI updates while staying near the local 20 RPM guard.
            await asyncio.sleep(interval)

    @timed_step
    async def _submit_with_retry(self, payload: dict, mode_desc: str, progress_callback=None) -> str:
        last_error_code = ""
        for attempt in range(self.max_retries):
            if self.shutdown_event and self.shutdown_event.is_set():
                raise RuntimeError("Video generation cancelled by user")

            try:
                await asyncio.to_thread(get_rate_limiter().acquire)
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        requests.post,
                        f"{BASE_URL}/videos",
                        headers=self.headers,
                        json=payload,
                        timeout=(15, 90),
                    ),
                    timeout=120,
                )

                if resp.status_code in (200, 201, 202):
                    result = resp.json()
                    if self.is_modern:
                        # Agnes Video 2.5 polling is keyed by video_id + model_name.
                        video_id = result.get("video_id")
                    else:
                        video_id = (
                            result.get("video_id")
                            or result.get("task_id")
                            or result.get("id")
                        )
                    if video_id:
                        return video_id
                    raise RuntimeError(
                        f"Agnes video submit returned no usable video_id: {result}"
                    )

                if resp.status_code == 429 or resp.status_code in {500, 502, 503, 504, 520, 522, 524}:
                    response_text = resp.text[:1000]
                    try:
                        response_data = resp.json()
                    except ValueError:
                        response_data = {}
                    last_error_code = str(response_data.get("code") or "").strip().lower()
                    queue_full = last_error_code == "video_queue_full"
                    retry_after = resp.headers.get("Retry-After")
                    # Agnes documents 503/video_queue_full as transient busy responses.
                    # Prefer server-provided Retry-After; otherwise use exponential
                    # backoff so repeated workers do not retry at the same moment.
                    if retry_after:
                        try:
                            delay = float(retry_after)
                        except ValueError:
                            delay = self.retry_base_delay * (2 ** attempt)
                    else:
                        delay = self.retry_base_delay * (2 ** attempt)
                    delay = max(1.0, min(delay, 300.0))
                    response_hint = response_text[:300].replace("\n", " ").replace("\r", " ")
                    queue_hint = " [video queue full]" if queue_full else ""
                    if progress_callback:
                        progress_callback("queue_retry", 0, f"Agnes busy; retry {attempt + 1}/{self.max_retries} in {delay:.0f}s")
                    logger.warning(
                        "[AgnesVideo] HTTP %s on %s; retry %d/%d in %.0fs%s%s",
                        resp.status_code,
                        mode_desc,
                        attempt + 1,
                        self.max_retries,
                        delay,
                        queue_hint,
                        f": {response_hint}" if response_hint else "",
                    )
                    # The modern 2.5 Flash free queue is best-effort and can remain
                    # saturated for minutes. Let submit_video switch to v2.0 on the
                    # first explicit queue-full response instead of sleeping/retrying.
                    if queue_full and self.is_modern:
                        raise RuntimeError(
                            "[AgnesVideo] video queue is full; trigger provider fallback"
                        )
                    if attempt + 1 < self.max_retries:
                        await asyncio.sleep(delay)
                        continue
                    break

                # Preserve the provider's structured validation error. The UI previously
                # reduced responses such as {"detail":[{"loc":[...],"msg":"Field required"}]}
                # to only "Field required", hiding which field was actually missing.
                try:
                    error_data = resp.json()
                    if isinstance(error_data, dict):
                        detail = error_data.get("detail")
                        if isinstance(detail, list):
                            parts = []
                            for item in detail[:10]:
                                if isinstance(item, dict):
                                    loc = item.get("loc")
                                    msg = item.get("msg") or item.get("detail")
                                    parts.append(f"{loc}: {msg}" if loc else str(msg))
                                else:
                                    parts.append(str(item))
                            error_text = "; ".join(parts) or resp.text[:1000]
                        elif isinstance(detail, (dict, str)):
                            error_text = json.dumps(detail, ensure_ascii=False) if isinstance(detail, dict) else detail
                        else:
                            error_text = json.dumps(error_data, ensure_ascii=False)[:1000]
                    else:
                        error_text = resp.text[:1000]
                except (ValueError, TypeError):
                    error_text = resp.text[:1000]
                diagnostic = (
                    f"endpoint={BASE_URL}/videos; model={self.model}; mode={mode_desc}; "
                    f"prompt_present={'prompt' in payload}; prompt_len={len(str(payload.get('prompt') or ''))}; "
                    f"payload_keys={','.join(sorted(payload.keys()))}"
                )
                raise RuntimeError(
                    f"Agnes video submit failed (HTTP {resp.status_code}): {error_text} [{diagnostic}]"
                )

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, asyncio.TimeoutError) as exc:
                delay = min(self.retry_base_delay * (attempt + 1), 300.0)
                logger.warning(
                    "[AgnesVideo] Transient network error on %s: %s; retry in %.0fs",
                    mode_desc, exc, delay,
                )
                await asyncio.sleep(delay)
            finally:
                try:
                    resp.close()
                except (NameError, AttributeError):
                    pass

        if last_error_code == "video_queue_full":
            raise RuntimeError(
                "[AgnesVideo] Agnes video queue is full after "
                f"{self.max_retries} attempts. The provider is temporarily overloaded; "
                "please retry later."
            )
        raise RuntimeError(
            f"[AgnesVideo] {mode_desc}: Agnes remained unavailable after "
            f"{self.max_retries} attempts. The service may be busy; please retry later."
        )

    @timed_step
    async def generate_single_video(
        self,
        prompt: str,
        reference_image_paths: Optional[Sequence[str]] = None,
        duration: Optional[int] = None,
        width: int = 1152,
        height: int = 648,
        seed: Optional[int] = None,
        negative_prompt: Optional[str] = None,
        progress_callback=None,
        **kwargs,
    ) -> VideoOutput:
        video_id = await self.submit_video(
            prompt=prompt,
            reference_image_paths=reference_image_paths,
            duration=duration,
            width=width,
            height=height,
            seed=seed,
            negative_prompt=negative_prompt,
            **kwargs,
        )
        return await self.wait_for_video(video_id, progress_callback)

    @timed_step
    async def submit_video(
        self,
        prompt: str,
        reference_image_paths: Optional[Sequence[str]] = None,
        duration: Optional[int] = None,
        width: int = 1152,
        height: int = 648,
        seed: Optional[int] = None,
        negative_prompt: Optional[str] = None,
        mode: Optional[str] = None,
        progress_callback=None,
        **kwargs,
    ) -> str:
        resolved_refs = [
            await self._resolve_image_ref(p)
            for p in (reference_image_paths or ())
        ]
        requested_mode = str(mode or "").strip().lower()
        # Fail locally with an explicit diagnostic instead of allowing the provider
        # to report the opaque FastAPI "body.prompt: Field required" error.
        prompt = str(prompt or "").strip()
        if not prompt:
            raise ValueError("Video prompt is empty before Agnes API request")

        if self.is_modern:
            seconds = self._modern_seconds(duration)
            payload = {
                "model": self.model,
                "prompt": prompt,
                "mode": (
                    "text" if not resolved_refs
                    else "keyframe" if requested_mode in {"i2v", "ti2vid", "img2video"} and len(resolved_refs) == 1
                    else "keyframe" if requested_mode in {"keyframes", "keyframe"} and len(resolved_refs) in {1, 2}
                    else "reference"
                ),
                "seconds": str(seconds),
                "size": "720P" if self.model == "agnes-video-2.5-flash" else kwargs.get("size", "720P"),
                "aspect_ratio": self._aspect_ratio(width, height),
                "n": 1,
            }
            if seed is not None:
                payload["seed"] = seed
            if len(resolved_refs) == 1:
                if payload["mode"] == "keyframe":
                    payload["first_frame"] = resolved_refs[0]
                else:
                    payload["images"] = [resolved_refs[0]]
                    if "<Picture 1>" not in payload["prompt"]:
                        payload["prompt"] = "<Picture 1> " + payload["prompt"]
            elif len(resolved_refs) == 2:
                payload["first_frame"] = resolved_refs[0]
                payload["last_frame"] = resolved_refs[1]
            elif len(resolved_refs) > 2:
                payload["images"] = resolved_refs[:5]
                if "<Picture 1>" not in payload["prompt"]:
                    payload["prompt"] = "<Picture 1> " + payload["prompt"]

            mode_desc = payload["mode"]
            logger.info(
                "[AgnesVideo] POST %s payload_keys=%s prompt_present=%s prompt_len=%d mode=%s refs=%d",
                f"{BASE_URL}/videos", sorted(payload.keys()), "prompt" in payload,
                len(payload["prompt"]), mode_desc, len(resolved_refs),
            )
        else:
            num_frames, frame_rate = self._get_frame_config(duration, width, height)
            payload = {
                "model": self.model,
                "prompt": prompt,
                "width": width,
                "height": height,
                "num_frames": num_frames,
                "frame_rate": frame_rate,
            }
            if seed is not None:
                payload["seed"] = seed
            if negative_prompt:
                payload["negative_prompt"] = negative_prompt

            if len(resolved_refs) == 1:
                payload["image"] = resolved_refs[0]
                payload["mode"] = "ti2vid"
                mode_desc = "image-to-video"
            elif len(resolved_refs) > 1:
                payload["extra_body"] = {
                    "image": resolved_refs,
                    "mode": "keyframes",
                }
                mode_desc = f"keyframes ({len(resolved_refs)} frames)"
            else:
                mode_desc = "text-to-video"

            logger.info("[AgnesVideo] %s: %s", mode_desc, prompt[:80])

        try:
            return await self._submit_with_retry(payload, mode_desc, progress_callback=progress_callback)
        except RuntimeError as exc:
            # The free 2.5 Flash queue is frequently saturated. Do not make the
            # user wait through all retries when the legacy free video model is
            # available as a compatible fallback.
            if self.is_modern and "video queue is full" in str(exc).lower():
                logger.warning(
                    "[AgnesVideo] 2.5 queue is full; falling back immediately to %s",
                    LEGACY_MODEL,
                )
                if progress_callback:
                    progress_callback(
                        "provider_fallback",
                        0,
                        f"Agnes 2.5 перегружен; переключение на {LEGACY_MODEL}",
                    )
                fallback = AgnesVideoAPI(
                    api_key=self.api_key,
                    model=LEGACY_MODEL,
                    default_duration=self.default_duration,
                    max_retries=2,
                    retry_base_delay=10.0,
                )
                fallback.shutdown_event = self.shutdown_event
                self._poll_api = fallback
                return await fallback.submit_video(
                    prompt=prompt,
                    reference_image_paths=reference_image_paths,
                    duration=duration,
                    width=width,
                    height=height,
                    seed=seed,
                    negative_prompt=negative_prompt,
                    mode=mode,
                    progress_callback=progress_callback,
                    **kwargs,
                )
            raise

    @timed_step
    async def wait_for_video(self, video_id: str, progress_callback=None) -> VideoOutput:
        poll_api = getattr(self, "_poll_api", self)
        final = await poll_api._poll_task(video_id, progress_callback=progress_callback)
        video_url = (
            final.get("url")
            or final.get("video_url")
            or (final.get("metadata") or {}).get("url")
        )
        if not video_url:
            data = final.get("data")
            if isinstance(data, dict):
                video_url = data.get("url") or data.get("video_url")
        if not video_url:
            raise RuntimeError(
                f"Agnes video: no URL in completed task: {json.dumps(final, ensure_ascii=False)[:2000]}"
            )
        logger.info("[AgnesVideo] Done: %s...", video_url[:80])
        return VideoOutput(fmt="url", ext="mp4", data=video_url)
