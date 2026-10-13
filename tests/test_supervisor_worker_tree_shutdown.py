import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import subprocess

def helper(platform, run):
    tree=ast.parse((Path(__file__).resolve().parents[1]/'local_agent/poller.py').read_text())
    node=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='_stop_owned_worker')
    ns={'Any':object,'os':SimpleNamespace(name=platform),'subprocess':SimpleNamespace(run=run,DEVNULL=subprocess.DEVNULL,TimeoutExpired=subprocess.TimeoutExpired)}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'shutdown','exec'),ns)
    return ns['_stop_owned_worker']

def test_windows_stops_owned_pid_tree_before_waiting():
    run=Mock();p=Mock(pid=1234);p.poll.return_value=None
    helper('nt',run)(p)
    assert run.call_args.args[0]==['taskkill.exe','/PID','1234','/T','/F']
    assert run.call_args.kwargs['shell'] is False
    p.terminate.assert_not_called()
    p.wait.assert_called_once_with(timeout=3)

def test_exited_worker_is_not_killed():
    run=Mock();p=Mock(pid=1234);p.poll.return_value=0
    helper('nt',run)(p)
    run.assert_not_called()

def test_non_windows_keeps_existing_graceful_shutdown():
    run=Mock();p=Mock();p.poll.return_value=None
    helper('posix',run)(p)
    run.assert_not_called();p.terminate.assert_called_once();p.wait.assert_called_once_with(timeout=8)

def test_non_windows_timeout_escalates_only_owned_process():
    run=Mock();p=Mock();p.poll.return_value=None
    p.wait.side_effect=[subprocess.TimeoutExpired('worker',8),None]
    helper('posix',run)(p)
    p.kill.assert_called_once()
