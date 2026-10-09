"""Crash-safe local checkpoint storage for long-running video projects."""
from __future__ import annotations

import json
import os
import pathlib
import re
import tempfile
from datetime import datetime, timezone
from threading import Lock, RLock
from typing import Any

ALLOWED_SCENE_STATES = {"pending", "queued", "claimed", "running", "validating", "completed", "retry_wait", "failed", "paused", "cancelled"}
_SAFE_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class CheckpointStore:
    _locks_guard = Lock()
    _path_locks: dict[str, RLock] = {}
    """Persist state atomically; media files are referenced, never embedded."""

    def __init__(self, workspace: str | os.PathLike[str], project_id: str):
        if not isinstance(project_id, str) or not _SAFE_PROJECT_ID.fullmatch(project_id):
            raise ValueError("Invalid project_id")
        workspace_root = pathlib.Path(workspace).resolve()
        candidate_root = workspace_root / project_id
        resolved_root = candidate_root.resolve()
        if not resolved_root.is_relative_to(workspace_root):
            raise ValueError("Project checkpoint directory resolves outside the configured workspace")
        self.root = resolved_root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "checkpoint.json"
        self.events_path = self.root / "events.jsonl"
        lock_key = str(self.path.resolve())
        with self._locks_guard:
            self._lock = self._path_locks.setdefault(lock_key, RLock())

    @staticmethod
    def _reject_symlink(path: pathlib.Path, label: str) -> None:
        # Checkpoint and event files must remain regular files inside the
        # project directory; following a pre-planted symlink could read or
        # append data outside the configured workspace.
        if path.is_symlink():
            raise ValueError(f"{label} must not be a symlink")

    def load(self) -> dict[str, Any] | None:
        with self._lock:
            self._reject_symlink(self.path, "Checkpoint file")
            if not self.path.exists():
                return None
            try:
                with self.path.open("r", encoding="utf-8") as stream:
                    data = json.load(stream)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                # Leave the damaged checkpoint untouched for manual recovery.
                raise ValueError(
                    f"Checkpoint is unreadable or truncated at {self.path.name}; "
                    "the original file was preserved. Restore a known-good copy or inspect it before retrying."
                ) from exc
            if (not isinstance(data, dict)
                    or isinstance(data.get("schema_version"), bool)
                    or not isinstance(data.get("schema_version"), int)
                    or data.get("schema_version") != 1
                    or not isinstance(data.get("scenes"), dict)
                    or not isinstance(data.get("manifest"), dict)
                    or not isinstance(data.get("project_id"), str)
                    or not _SAFE_PROJECT_ID.fullmatch(data.get("project_id", ""))):
                raise ValueError("Checkpoint is malformed or uses an unsupported schema")
            if data["manifest"].get("project_id") != data["project_id"]:
                raise ValueError("Checkpoint manifest/project_id mismatch")
            project_status = data.get("status")
            if not isinstance(project_status, str) or project_status not in {
                "queued", "running", "paused", "completed", "failed", "cancelled"
            }:
                raise ValueError("Checkpoint contains an invalid project status")
            for scene_id, scene in data["scenes"].items():
                if not isinstance(scene_id, str) or not _SAFE_PROJECT_ID.fullmatch(scene_id) or not isinstance(scene, dict):
                    raise ValueError("Checkpoint contains a malformed scene entry")
                scene_status = scene.get("status")
                if not isinstance(scene_status, str) or scene_status not in ALLOWED_SCENE_STATES:
                    raise ValueError(f"Checkpoint scene {scene_id!r} has an invalid status")
                attempts = scene.get("attempts")
                if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
                    raise ValueError(f"Checkpoint scene {scene_id!r} has invalid attempts")
                for field in ("video_path", "final_frame_path", "video_sha256", "frame_sha256", "input_frame_sha256", "error"):
                    value = scene.get(field)
                    if value is not None and not isinstance(value, str):
                        raise ValueError(f"Checkpoint scene {scene_id!r} has invalid {field}")
            return data

    def initialize(self, manifest: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            existing = self.load()
            if existing is not None:
                if existing.get("project_id") != manifest.get("project_id"):
                    raise ValueError("Checkpoint project_id mismatch")
                if existing.get("manifest") != manifest:
                    raise ValueError("Manifest differs from the checkpoint; refusing unsafe resume")
                expected_ids = {scene.get("scene_id") for scene in manifest.get("scenes", []) if isinstance(scene, dict)}
                if expected_ids != set(existing["scenes"]):
                    raise ValueError("Checkpoint scene set does not match manifest")
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
                        "video_sha256": None, "frame_sha256": None,
                        "input_frame_sha256": None, "error": None,
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
            # Unique temp files avoid collisions between interrupted writes or
            # separate store instances. The last complete checkpoint remains intact
            # until the atomic replace succeeds; orphaned temps are never auto-loaded.
            descriptor, temp_name = tempfile.mkstemp(
                prefix="checkpoint.", suffix=".tmp", dir=str(self.root)
            )
            temp_path = pathlib.Path(temp_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                    json.dump(state, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_path, self.path)
            except BaseException:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise

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
            self._reject_symlink(self.events_path, "Event log")
            # Keep bounded local diagnostics: current log plus two rotated files.
            max_log_bytes = 5 * 1024 * 1024
            if self.events_path.exists() and self.events_path.stat().st_size >= max_log_bytes:
                oldest = self.root / "events.jsonl.2"
                middle = self.root / "events.jsonl.1"
                try:
                    oldest.unlink(missing_ok=True)
                    if middle.exists():
                        os.replace(middle, oldest)
                    os.replace(self.events_path, middle)
                except OSError:
                    # Logging must not destroy checkpoint correctness if rotation fails.
                    pass
            with self.events_path.open("a", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()