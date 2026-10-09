"""Crash-safe local checkpoint storage for long-running video projects."""
from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime, timezone
from threading import RLock
from typing import Any

ALLOWED_SCENE_STATES = {"pending", "queued", "claimed", "running", "validating", "completed", "retry_wait", "failed", "paused", "cancelled"}

class CheckpointStore:
    """Persist state atomically; media files are referenced, never embedded."""

    def __init__(self, workspace: str | os.PathLike[str], project_id: str):
        if not project_id or any(ch in project_id for ch in ("/", chr(92), "..")):
            raise ValueError("Invalid project_id")
        self.root = pathlib.Path(workspace).resolve() / project_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "checkpoint.json"
        self.events_path = self.root / "events.jsonl"
        self._lock = RLock()

    def load(self) -> dict[str, Any] | None:
        with self._lock:
            if not self.path.exists():
                return None
            with self.path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
            if not isinstance(data, dict) or not isinstance(data.get("scenes"), dict):
                raise ValueError("Checkpoint is malformed")
            return data

    def initialize(self, manifest: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            existing = self.load()
            if existing is not None:
                if existing.get("manifest", {}).get("project_id") != manifest.get("project_id"):
                    raise ValueError("Checkpoint project_id mismatch")
                return existing
            state = {
                "schema_version": 1,
                "project_id": manifest["project_id"],
                "manifest": manifest,
                "status": "queued",
                "created_at": self._now(),
                "updated_at": self._now(),
                "current_scene_index": 0,
                "scenes": {
                    scene["scene_id"]: {
                        "index": index, "status": "pending", "attempts": 0,
                        "video_path": None, "final_frame_path": None,
                        "video_sha256": None, "frame_sha256": None, "error": None,
                    }
                    for index, scene in enumerate(manifest["scenes"], start=1)
                },
                "final_video_path": None,
                "error": None,
            }
            self.save(state)
            self.event("project_initialized", {"scene_count": len(manifest["scenes"])})
            return state

    def save(self, state: dict[str, Any]) -> None:
        with self._lock:
            state["updated_at"] = self._now()
            temp_path = self.path.with_suffix(".json.tmp")
            with temp_path.open("w", encoding="utf-8", newline="") as stream:
                json.dump(state, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)

    def update_scene(self, state: dict[str, Any], scene_id: str, **updates: Any) -> None:
        with self._lock:
            if scene_id not in state["scenes"]:
                raise KeyError(f"Unknown scene_id: {scene_id}")
            if "status" in updates and updates["status"] not in ALLOWED_SCENE_STATES:
                raise ValueError("Invalid scene status: " + str(updates["status"]))
            state["scenes"][scene_id].update(updates)
            self.save(state)

    def event(self, name: str, payload: dict[str, Any] | None = None) -> None:
        record = {"timestamp": self._now(), "event": name, "payload": payload or {}}
        with self._lock:
            with self.events_path.open("a", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()