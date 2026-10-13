import ast
from pathlib import Path


def status_label(**kwargs):
    source = (Path(__file__).resolve().parents[1] / "local_agent/poller.py").read_text()
    tree = ast.parse(source)
    node = next(item for item in tree.body
                if isinstance(item, ast.FunctionDef)
                and item.name == "_mailbox_status_label")
    namespace = {"_MAILBOX_STALE_SECONDS": 900}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "status", "exec"), namespace)
    return namespace["_mailbox_status_label"](**kwargs)


def test_dead_process_is_not_reported_as_running():
    assert status_label(process_alive=False, task_claimed=False,
                        heartbeat_mtime=990, now_wall=1000,
                        started_at_wall=900) == "не запущен"


def test_fresh_heartbeat_confirms_idle_mailbox_liveness():
    result = status_label(process_alive=True, task_claimed=False,
                          heartbeat_mtime=990, now_wall=1000,
                          started_at_wall=900)
    assert result == "работает; heartbeat обновлён 10 с назад"


def test_stale_heartbeat_exposes_live_but_unresponsive_pid():
    result = status_label(process_alive=True, task_claimed=False,
                          heartbeat_mtime=0, now_wall=1000,
                          started_at_wall=0)
    assert result == "нет отклика: heartbeat не обновлялся 16 мин"


def test_stale_heartbeat_preserves_claimed_task_context():
    result = status_label(process_alive=True, task_claimed=True,
                          heartbeat_mtime=0, now_wall=1000,
                          started_at_wall=0)
    assert result == "задача числится активной; heartbeat не обновлялся 16 мин"


def test_startup_without_first_heartbeat_has_grace_state():
    result = status_label(process_alive=True, task_claimed=False,
                          heartbeat_mtime=None, now_wall=100,
                          started_at_wall=50)
    assert result == "запускается; heartbeat ещё не получен"
