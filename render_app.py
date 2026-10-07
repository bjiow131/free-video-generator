"""Container/local entrypoint for the Agnes Video Generator server.

The application is intentionally single-user and local; there is no public
account/session router to mount here.
"""
import os
import uvicorn

from server import app


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8765")),
        log_level="info",
    )
