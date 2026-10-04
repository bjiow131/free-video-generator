"""core/providers — Video generation provider abstraction.

This package provides a clean abstraction layer for video generation providers.
Currently supports Google Flow as the primary provider.
"""

from core.providers.base_provider import BaseVideoProvider, VideoOutput
from core.providers.factory import get_video_provider

__all__ = [
    "BaseVideoProvider",
    "VideoOutput",
    "get_video_provider",
]
