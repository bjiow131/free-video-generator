"""Render entrypoint for the public AISTUDIO workspace.

The original server.py exposes the main Agnes Video Generator API.
This wrapper additionally mounts the public AISTUDIO router used by
static/ai-studio.html at /api/public/*.
"""
import os
import uvicorn

from server import app
from core.public_api import router as public_router

app.include_router(public_router)

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8765")),
        log_level="info",
    )
