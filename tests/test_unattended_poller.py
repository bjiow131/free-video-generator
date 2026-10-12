"""Regression: the private GitHub mailbox does not ask for YES with local authorization."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from local_agent import poller


class Client:
    def __init__(self, task, sha='stable-manifest'):
        self.task = task
        self.sha = sha
        self.results = []

    def fetch_desired_task(self):
        return self.task, self.sha

    def publish_result(self, task_id, result):
        self.results.append((task_id, result))
        return 'mock-commit'


def task(operation, args=None, *, approval=True):
    return SimpleNamespace(
        task_id='autonomous-safe-001', operation=operation, arguments=args or {},
        created_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        requires_local_approval=approval,
    )


def policy(**options):
    return dict(enabled=True, allow_octava=False, allow_blender=False,
                allow_tests=False, **options)


def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(poller, '_ensure_agent_dir', lambda: tmp_path)
    monkeypatch.setattr(poller, 'write_report', lambda *_a, **_kw: tmp_path / 'report.json')
    monkeypatch.setattr(poller, 'notify_user', lambda **_kw: True)
    monkeypatch.setattr('builtins.input', lambda _prompt: pytest.fail('unexpected YES prompt'))


def test_diagnostics_run_noninteractive_without_confirmation(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    p = policy()
    monkeypatch.setattr(poller, 'load_policy', lambda: p)
    run = []
    monkeypatch.setattr(poller, '_run_blender_preflight', lambda _a: run.append('ok') or {'status': 'completed', 'blender': True})
    client = Client(task('blender_preflight'))
    poller._run_one(client, client.task, 'stable-manifest')
    assert run == ['ok']
    assert client.results[-1][1]['status'] == 'completed'


def test_patch_never_unattended_and_does_not_prompt(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(poller, 'load_policy', lambda: policy())
    monkeypatch.setattr(poller, '_apply_patch', lambda *_a, **_kw: pytest.fail('patch executed'))
    client = Client(task('apply_patch', {'patch': 'diff --git a/x b/x\n'}))
    poller._run_one(client, client.task, 'stable-manifest')
    assert client.results[-1][1]['reason'] == 'operation_not_authorized_for_unattended_mode'


def test_unauthorized_blender_creation_is_blocked(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(poller, 'load_policy', lambda: policy())
    client = Client(task('blender_mia_skeleton', {'project_name': 'mia'}))
    poller._run_one(client, client.task, 'stable-manifest')
    assert client.results[-1][1]['status'] == 'blocked'


def test_octava_requires_permission_and_calls_budget_before_api(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    p = dict(enabled=True, allow_octava=True, allow_blender=False, allow_tests=False)
    monkeypatch.setattr(poller, 'load_policy', lambda: p)
    calls = []
    monkeypatch.setattr(poller, 'reserve_octava_call', lambda: calls.append('reserve'))
    monkeypatch.setattr(poller, '_run_octava_advice', lambda _a: calls.append('api') or {'status': 'completed', 'advice': 'OK'})
    client = Client(task('octava_advice', {'prompt': 'OK'}))
    poller._run_one(client, client.task, 'stable-manifest')
    assert calls == ['reserve', 'api']
    assert client.results[-1][1]['status'] == 'completed'


def test_remote_approval_false_never_bypasses_local_policy(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(poller, 'load_policy', lambda: policy())
    client = Client(task('doctor', approval=False))
    poller._run_one(client, client.task, 'stable-manifest')
    assert client.results[-1][1]['reason'] == 'remote_approval_disabled'


def test_changed_manifest_does_not_run(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(poller, 'load_policy', lambda: policy())
    client = Client(task('doctor'), sha='changed-manifest')
    monkeypatch.setitem(poller.SUPPORTED_HANDLERS, 'doctor', lambda: pytest.fail('stale task executed'))
    poller._run_one(client, client.task, 'original-manifest')
    assert client.results[-1][1]['status'] == 'superseded'


def test_mia_blockout_defaults_to_five_second_review(monkeypatch, tmp_path):
    from local_agent import blender_workflow
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(poller, 'load_policy', lambda: policy(allow_blender=True))
    preview = tmp_path / 'preview.png'
    preview.write_bytes(b'preview')
    seen = []
    monkeypatch.setattr(blender_workflow, 'create_mia_blockout',
                        lambda name, **kw: seen.append((name, kw)) or {
                            'status': 'completed', 'preview_path': str(preview), 'duration_seconds': 5})
    result = poller._run_blender_mia_blockout({'project_name': 'S01E01_SC01_RELEASE'})
    assert seen == [('S01E01_SC01_RELEASE', {'overwrite': False, 'duration_seconds': 5})]
    assert result['duration_seconds'] == 5
    assert result['preview_png_base64']


def test_mia_full_render_requires_explicit_flag(monkeypatch, tmp_path):
    from local_agent import blender_workflow
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(poller, 'load_policy', lambda: policy(allow_blender=True))
    called = []
    monkeypatch.setattr(blender_workflow, 'create_mia_blockout',
                        lambda *a, **kw: called.append(True) or {'status': 'completed'})
    blocked = poller._run_blender_mia_blockout({
        'project_name': 'S01E01_SC01_RELEASE', 'duration_seconds': 60})
    assert blocked['status'] == 'rejected'
    assert not called
    result = poller._run_blender_mia_blockout({
        'project_name': 'S01E01_SC01_RELEASE', 'duration_seconds': 60,
        'allow_full_render': True})
    assert result['status'] == 'completed'
    assert called == [True]
