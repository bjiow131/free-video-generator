"""Google Veo 3.1 video provider."""
import asyncio
import os
import tempfile
from google import genai
from google.genai import types

class GoogleVideoProvider:
    def __init__(self, api_key=None, model="veo-3.1-generate-preview"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model

    async def generate(self, prompt, reference_path=None, aspect_ratio="16:9", resolution="720p"):
        if not self.api_key:
            raise RuntimeError("Google Gemini API key не настроен")
        return await asyncio.to_thread(
            self._sync, prompt, reference_path, aspect_ratio, resolution
        )

    def _sync(self, prompt, reference_path, aspect_ratio, resolution):
        client = genai.Client(api_key=self.api_key)
        kwargs = {
            "model": self.model,
            "prompt": prompt,
            "config": types.GenerateVideosConfig(
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                number_of_videos=1,
            ),
        }
        if reference_path:
            image = types.Image.from_file(location=reference_path)
            kwargs["image"] = image

        operation = client.models.generate_videos(**kwargs)
        for _ in range(36):
            if operation.done:
                break
            import time
            time.sleep(5)
            operation = client.operations.get(operation)

        if not operation.done:
            raise RuntimeError("Генерация видео выполняется слишком долго")

        generated = operation.response.generated_videos[0]
        path = os.path.join(
            tempfile.gettempdir(), "ai_studio_veo_%s.mp4" % os.urandom(8).hex()
        )
        client.files.download(file=generated.video, destination=path)
        return path
