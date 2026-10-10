from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_agent import workbench_cli


def test_exit_choice_does_not_start_any_task():
    assert workbench_cli.run_menu_choice("0") == {"status": "exit"}


def test_unknown_choice_is_rejected_without_side_effects():
    assert workbench_cli.run_menu_choice("run arbitrary command") == {
        "status": "invalid_choice",
        "choice": "run arbitrary command",
    }


def test_forest_operation_requires_confirmation_before_project_prompt(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(workbench_cli, "discover_blender", lambda: {"status": "ready"})
    answers = iter(["n"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert workbench_cli.run_menu_choice("1") == {"status": "cancelled"}


def test_story_plan_source_must_be_a_regular_file(monkeypatch, tmp_path: Path):
    link = tmp_path / "plan.json"
    target = tmp_path / "target.json"
    target.write_text(json.dumps({}), encoding="utf-8")
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this Windows account.")
    monkeypatch.setattr("builtins.input", lambda _prompt="": str(link))
    with pytest.raises(ValueError, match="regular file"):
        workbench_cli.run_menu_choice("7")


def test_knowledge_search_is_read_only(monkeypatch):
    monkeypatch.setattr(workbench_cli, "list_topics", lambda: [{"id": "materials"}])
    monkeypatch.setattr(workbench_cli, "search_knowledge", lambda query: [{"query": query}])
    answers = iter(["materials"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert workbench_cli.run_menu_choice("9") == [{"query": "materials"}]
