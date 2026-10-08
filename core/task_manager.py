"""
core/task_manager.py — Agnes Video Generator v2.1 Recovery Edition

Добавлено:
- event log (events.jsonl)
- checkpoint recovery
- безопасное восстановление после F5/перезапуска
- сохранение совместимости с v2.0/v3.0
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

from core.config import get_working_dir
from models.task import (
    BaseTaskState,
    CreativeVideoTask,
    ManuscriptVideoTask,
    ManuscriptParagraph,
    SceneTask,
    StepStatus,
    SubtitleConfig,
    TaskType,
    parse_task_state,
)

logger = logging.getLogger(__name__)


class TaskManager:
    """
    Менеджер состояния задач.
    """

    def __init__(self, task_id: str, dir_name: str = None):
        self.task_id = task_id
        self.dir_name = dir_name or task_id
        if (
            not self.dir_name
            or os.path.basename(self.dir_name) != self.dir_name
            or self.dir_name in {".", ".."}
            or "/" in self.dir_name
            or chr(92) in self.dir_name
        ):
            raise ValueError("Invalid task directory name")

        working_dir = os.path.realpath(get_working_dir())
        self.task_dir = os.path.realpath(os.path.join(working_dir, self.dir_name))
        if os.path.commonpath([working_dir, self.task_dir]) != working_dir:
            raise ValueError("Task directory escapes working directory")

        self._task_file = os.path.join(
            self.task_dir,
            "task_state.json"
        )

        self._events_file = os.path.join(
            self.task_dir,
            "events.jsonl"
        )

        self._checkpoint_file = os.path.join(
            self.task_dir,
            "checkpoint.json"
        )

        self._state: Optional[BaseTaskState] = None


    def _ensure_dir(self):
        os.makedirs(
            self.task_dir,
            exist_ok=True
        )


    def _write_atomic(self, path, data):
        """
        Безопасная запись файла.
        """

        directory = os.path.dirname(path)

        self._ensure_dir()

        fd, tmp = tempfile.mkstemp(
            dir=directory,
            suffix=".tmp"
        )

        try:
            with os.fdopen(
                fd,
                "w",
                encoding="utf-8"
            ) as f:
                json.dump(
                    data,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            os.replace(
                tmp,
                path
            )

        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise


    def _log_event(
        self,
        action: str,
        data: dict = None
    ):
        """Append a durable JSONL event to the task history."""
        self._ensure_dir()
        event = {
            "time": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "data": data or {},
        }
        with open(self._events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())


    def create(
        self,
        state: BaseTaskState
    ) -> BaseTaskState:

        self._ensure_dir()

        self._state = state
        self._state.task_id = self.task_id

        self._save()

        self.create_checkpoint()

        self._log_event(
            "task_created",
            {
                "task_id": self.task_id
            }
        )

        return self._state


    def load(self) -> Optional[BaseTaskState]:

        if not os.path.exists(
            self._task_file
        ):
            return None

        try:
            with open(
                self._task_file,
                "r",
                encoding="utf-8"
            ) as f:
                data = json.load(f)

            self._state = parse_task_state(
                data
            )
            if self._normalize_recovered_state():
                self._save()
                self._log_event("task_recovery_normalized")


            if isinstance(
                self._state,
                (CreativeVideoTask, ManuscriptVideoTask)
            ):
                subtitle_cfg = getattr(
                    self._state,
                    "subtitle_config",
                    None
                )

                if not subtitle_cfg:
                    raw_audio = data.get(
                        "audio_config",
                        {}
                    )

                    raw_style = raw_audio.get(
                        "subtitle_style"
                    )

                    if raw_style:
                        from models.task import SubtitleStyle

                        self._state.subtitle_config = SubtitleConfig(
                            enabled=True,
                            style=SubtitleStyle(**raw_style)
                        )

                        self._save()


            if isinstance(
                self._state,
                CreativeVideoTask
            ):
                self._state.scenes = [
                    SceneTask(**s)
                    if isinstance(s, dict)
                    else s
                    for s in (
                        data.get("scenes")
                        or self._state.scenes
                    )
                ]


            self._log_event(
                "task_loaded"
            )

            return self._state


        except Exception as e:
            logger.warning(
                f"Load failed: {e}"
            )

            return self.restore_checkpoint()

    def _normalize_recovered_state(self) -> bool:
        """Reset in-flight task steps after a process restart."""
        if not self._state:
            return False
        changed = False
        in_flight = {StepStatus.RUNNING, StepStatus.QUEUED}
        if self._state.status in in_flight:
            self._state.status = StepStatus.PENDING
            changed = True
        for field_name in type(self._state).model_fields:
            if not field_name.startswith("step_"):
                continue
            value = getattr(self._state, field_name, None)
            if value in in_flight:
                setattr(self._state, field_name, StepStatus.PENDING)
                changed = True
        if isinstance(self._state, CreativeVideoTask):
            for scene in self._state.scenes:
                if scene.status in in_flight:
                    scene.status = StepStatus.PENDING
                    changed = True
                if scene.video_status in in_flight:
                    scene.video_status = StepStatus.PENDING
                    changed = True
        return changed


    def _save(self):
        """
        Сохранение текущего состояния.
        """

        if self._state:
            self._write_atomic(
                self._task_file,
                self._state.model_dump()
            )


    def create_checkpoint(self):
        """
        Создание точки восстановления.
        """

        if not self._state:
            return

        self._write_atomic(
            self._checkpoint_file,
            self._state.model_dump()
        )

        self._log_event(
            "checkpoint_created",
            {
                "status": str(self._state.status)
            }
        )


    def restore_checkpoint(self):
        """
        Восстановление последнего checkpoint.
        """

        if not os.path.exists(
            self._checkpoint_file
        ):
            return None

        try:
            with open(
                self._checkpoint_file,
                "r",
                encoding="utf-8"
            ) as f:
                data = json.load(f)


            self._state = parse_task_state(
                data
            )

            self._normalize_recovered_state()

            self._save()

            self._log_event(
                "checkpoint_restored"
            )

            return self._state


        except Exception as e:
            logger.warning(
                f"Checkpoint restore failed: {e}"
            )

            return None



    def update_step(
        self,
        step_name: str,
        status: StepStatus
    ):

        if self._state:

            setattr(
                self._state,
                step_name,
                status
            )

            self._log_event(
                "step_updated",
                {
                    "step": step_name,
                    "status": str(status)
                }
            )

            self._save()



    def update_scene(
        self,
        scene: SceneTask
    ):

        if self._state and isinstance(
            self._state,
            CreativeVideoTask
        ):

            for i, s in enumerate(
                self._state.scenes
            ):

                if s.index == scene.index:

                    self._state.scenes[i] = scene

                    self._log_event(
                        "scene_updated",
                        {
                            "scene": scene.index
                        }
                    )

                    self.create_checkpoint()

                    self._save()

                    return



    def update_state(
        self,
        **kwargs
    ):

        if not self._state:
            return


        for key, value in kwargs.items():

            if hasattr(
                self._state,
                key
            ):

                if key == "scenes" and isinstance(
                    value,
                    list
                ):
                    value = [
                        SceneTask(**s)
                        if isinstance(s, dict)
                        else s
                        for s in value
                    ]


                elif key == "paragraphs" and isinstance(
                    value,
                    list
                ):

                    value = [
                        ManuscriptParagraph(**p)
                        if isinstance(p, dict)
                        else p
                        for p in value
                    ]


                setattr(
                    self._state,
                    key,
                    value
                )


        self._log_event(
            "state_updated",
            {
                "fields": list(kwargs.keys())
            }
        )

        self.create_checkpoint()

        self._save()



    def get_state(self):
        return self._state



    def exists(self):
        return os.path.exists(
            self._task_file
        )



    def list_tasks(self):

        working_dir = get_working_dir()

        if not os.path.exists(
            working_dir
        ):
            return []


        tasks = []


        for name in os.listdir(
            working_dir
        ):

            task_file = os.path.join(
                working_dir,
                name,
                "task_state.json"
            )


            if os.path.exists(task_file):

                try:

                    with open(
                        task_file,
                        "r",
                        encoding="utf-8"
                    ) as f:
                        data = json.load(f)


                    tasks.append(
                        {
                            "task_id": data.get(
                                "task_id",
                                name
                            ),

                            "dir_name": name,

                            "task_type": data.get(
                                "task_type",
                                TaskType.CREATIVE
                            ),

                            "creative_name": data.get(
                                "creative_name",
                                ""
                            ),

                            "status": data.get(
                                "status",
                                "pending"
                            ),

                            "chaining_mode": data.get(
                                "chaining_mode",
                                "none"
                            )
                        }
                    )


                except Exception as e:

                    logger.debug(
                        f"Task listing failed: {e}"
                    )


        tasks.sort(
            key=lambda t: t.get(
                "dir_name",
                ""
            ),
            reverse=True
        )

        return tasks
