import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import Mock
import pytest

SOURCE = Path(__file__).parents[1] / 'local_agent' / 'poller.py'

@pytest.fixture
def ns(tmp_path):
    names = {'_computer_control_enabled', '_validate_computer_arguments', '_run_computer_control',
             '_cleanup_owned_orphans', 'recover_windows_services', '_supervisor_recovery_command',
             '_request_restart_and_open_studio'}
    nodes = [n for n in ast.parse(SOURCE.read_text()).body if isinstance(n, ast.FunctionDef) and n.name in names]
    class ProtocolError(ValueError): pass
    class PollerAlreadyRunning(RuntimeError): pass
    from types import SimpleNamespace
    namespace = dict(Path=Path, Any=object, ROOT=tmp_path, json=json,
                     os=SimpleNamespace(name='nt', environ={}), subprocess=SimpleNamespace(Popen=Mock(wraps=subprocess.Popen), run=Mock(), DEVNULL=subprocess.DEVNULL, STDOUT=subprocess.STDOUT, TimeoutExpired=subprocess.TimeoutExpired, list2cmdline=subprocess.list2cmdline),
                     ProtocolError=ProtocolError, PollerAlreadyRunning=PollerAlreadyRunning,
                     tempfile=tempfile, _redact_value=lambda x:x,
                     _ensure_agent_dir=lambda:tmp_path,
                     _process_creation_stamp=lambda pid:'new',
                     _acquire_instance_lock=Mock(), _studio_has_active_job=lambda:False)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'), namespace)
    return namespace

def test_default_denies_computer_execution(ns):
    assert not ns['_computer_control_enabled']()
    assert ns['_run_computer_control']({'program':sys.executable})['status']=='blocked'
    ns['subprocess'].Popen.assert_not_called()

def test_explicit_zero_revokes_launcher_grant(ns):
    (ns['ROOT']/'run_github_mailbox_agent.bat').write_text('set "LOCAL_AGENT_ALLOW_COMPUTER_CONTROL=1"')
    assert ns['_computer_control_enabled']()
    ns['os'].environ['LOCAL_AGENT_ALLOW_COMPUTER_CONTROL']='0'
    assert not ns['_computer_control_enabled']()

@pytest.mark.parametrize('args',[
    {'program':'x','arguments':'not-list'}, {'program':'x','timeout_seconds':True},
    {'program':'x','timeout_seconds':1801}, {'program':'x\0evil'},
    {'program':'x','arguments':['a\0b']}, {'program':'x','unknown':True},
])
def test_invalid_arguments_are_rejected(ns,args):
    with pytest.raises(ValueError): ns['_validate_computer_arguments'](args)

def test_control_runs_a_real_child_and_bounds_output(ns):
    ns['os'].environ['LOCAL_AGENT_ALLOW_COMPUTER_CONTROL']='1'
    result=ns['_run_computer_control']({'program':sys.executable,'arguments':['-c','print("x"*8000)']})
    assert result['status']=='completed' and result['output_truncated']
    assert len(result['stdout'])==4000
    assert ns['subprocess'].Popen.call_args.kwargs['shell'] is False

def test_recycled_pid_is_never_killed(ns):
    (ns['ROOT']/'services_owned.json').write_text(json.dumps({'schema_version':1,'services':[{'role':'mailbox','pid':123,'created':'old'}]}))
    ns['_cleanup_owned_orphans']()
    ns['subprocess'].run.assert_not_called()

def test_matching_owned_process_is_stopped_as_tree(ns):
    (ns['ROOT']/'services_owned.json').write_text(json.dumps({'schema_version':1,'services':[{'role':'mailbox','pid':123,'created':'new'}]}))
    ns['_cleanup_owned_orphans']()
    assert ns['subprocess'].run.call_args.args[0]==['taskkill.exe','/PID','123','/T','/F']

def test_recovery_does_not_start_a_second_supervisor(ns):
    ns['_acquire_instance_lock'].side_effect=[Mock(),ns['PollerAlreadyRunning']()]
    assert ns['recover_windows_services']()==0
    ns['subprocess'].Popen.assert_not_called()

def test_active_render_prevents_orphan_cleanup(ns):
    ns['_studio_has_active_job']=lambda:True
    ns['_cleanup_owned_orphans']=Mock()
    assert ns['recover_windows_services']()==0
    ns['_cleanup_owned_orphans'].assert_not_called()
    ns['subprocess'].Popen.assert_not_called()

def test_restart_does_not_open_browser(ns):
    ns['request_runtime_restart']=lambda _: {'status':'queued'}
    assert ns['_request_restart_and_open_studio']()['browser_open_requested'] is False
    supervisor=next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='supervise_windows')
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='webbrowser' for n in ast.walk(supervisor))
