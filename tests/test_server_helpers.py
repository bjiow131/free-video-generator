import asyncio

import pytest

import server
from models.task import StepStatus, TaskType


def test_parse_bg_color_rejects_invalid_values():
    assert server._parse_bg_color("(255, 0, 128)") == (255, 0, 128)
    assert server._parse_bg_color("black@0.5") == (0, 0, 0, 128)
    with pytest.raises(ValueError):
        server._parse_bg_color("(256, 0, 0)")
    with pytest.raises(ValueError):
        server._parse_bg_color("not-a-color")


def test_parse_duration_only_returns_duration_frame_map_key():
    assert server._parse_duration("каждый 5 секунд") == 5
    assert server._parse_duration("каждый 10 секунд") == 10
    assert server._parse_duration("каждый 7 секунд") == 5
    assert server._parse_duration("") in server.DURATION_FRAME_MAP


def test_parse_duration_rejects_empty_duration_map(monkeypatch):
    monkeypatch.setattr(server, "DURATION_FRAME_MAP", {})
    with pytest.raises(ValueError):
        server._parse_duration("5 секунд")


class _TaskManager:
    def __init__(self):
        self.statuses = []

    def update_state(self, **kwargs):
        self.statuses.append(kwargs["status"])


class _Pipeline:
    task_id = "cancel-test"
    _stop_event = asyncio.Event()


@pytest.mark.asyncio
async def test_cancel_while_queued_does_not_release_semaphore(monkeypatch):
    semaphore = server.WeightedSemaphore(1)
    semaphore.current = 1
    manager = _TaskManager()
    pipeline = _Pipeline()
    state = type("State", (), {"task_type": TaskType.SIMPLE})()

    monkeypatch.setattr(server, "_pipeline_semaphore", semaphore)
    monkeypatch.setitem(server._queued_tasks, pipeline.task_id, 1)

    task = asyncio.create_task(
        server._run_pipeline_with_concurrency(pipeline, state, manager)
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert semaphore.current == 1
    assert manager.statuses[-1] == StepStatus.PENDING
    assert pipeline.task_id not in server._queued_tasks
