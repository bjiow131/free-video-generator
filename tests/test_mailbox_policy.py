"""Offline unattended mailbox authorization without a local daily provider cap."""
import importlib.util
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

SPEC = importlib.util.spec_from_file_location('local_unattended_policy', Path(__file__).parents[1] / 'local_agent' / 'mailbox_policy.py')
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / 'agent'
    root.mkdir()
    monkeypatch.setattr(policy, '_ROOT', root)
    monkeypatch.setattr(policy, 'POLICY_FILE', root / '.local_agent' / 'mailbox_policy.json')
    return root


def test_default_is_disabled_and_safest(vault):
    assert policy.load_policy() == policy.default_policy()
    assert not policy.is_auto_authorized('doctor')
    assert not policy.is_auto_authorized('octava_advice')


def test_local_enable_accepts_diagnostics_and_never_arbitrary_patch(vault):
    value = dict(enabled=True, allow_octava=False, allow_blender=False, allow_tests=False, allow_asset_sync=False)
    assert policy.save_policy(value) == value
    assert policy.load_policy() == value
    for op in policy.READ_ONLY_OPERATIONS:
        assert policy.is_auto_authorized(op)
    for op in ('apply_patch', 'start', 'stop', 'backup', 'logs', 'blender_open_mia_project', 'run_script'):
        assert not policy.is_auto_authorized(op)
    assert not policy.is_auto_authorized('octava_advice')
    assert not policy.is_auto_authorized('blender_mia_skeleton')
    assert not policy.is_auto_authorized('sync_approved_assets')


def test_optional_permissions_are_independent(vault):
    value = dict(enabled=True, allow_octava=True, allow_blender=True, allow_tests=True, allow_asset_sync=False)
    policy.save_policy(value)
    assert policy.is_auto_authorized('octava_advice')
    assert policy.is_auto_authorized('test')
    assert policy.is_auto_authorized('save_story_plan')
    assert not policy.is_auto_authorized('apply_patch')
    value['enabled'] = False
    policy.save_policy(value)
    assert not policy.is_auto_authorized('octava_advice')


def test_asset_sync_needs_its_own_local_permission(vault):
    value = dict(enabled=True, allow_octava=False, allow_blender=False,
                 allow_tests=False, allow_asset_sync=False)
    policy.save_policy(value)
    assert not policy.is_auto_authorized('sync_approved_assets')

    value['allow_asset_sync'] = True
    policy.save_policy(value)
    assert policy.is_auto_authorized('sync_approved_assets')
    assert not policy.is_auto_authorized('apply_patch')
    assert not policy.is_auto_authorized('blender_mia_blockout')

    value['enabled'] = False
    policy.save_policy(value)
    assert not policy.is_auto_authorized('sync_approved_assets')


def test_legacy_policy_migrates_asset_sync_disabled(vault):
    old = dict(enabled=True, allow_octava=True, allow_blender=True, allow_tests=True)
    policy.POLICY_FILE.parent.mkdir(parents=True)
    policy.POLICY_FILE.write_text(json.dumps(old), encoding='utf-8')
    loaded = policy.load_policy()
    assert loaded == {**old, 'allow_asset_sync': False}


@pytest.mark.parametrize('bad', [
    {}, {'enabled': True, 'allow_octava': False},
    {'enabled': True, 'allow_octava': False, 'allow_blender': False, 'allow_tests': False, 'admin': True},
    {'enabled': 1, 'allow_octava': False, 'allow_blender': False, 'allow_tests': False},
])
def test_extra_or_wrong_type_rejected(vault, bad):
    with pytest.raises(policy.MailboxPolicyError):
        policy.save_policy(bad)


def test_corrupt_policy_does_not_disable_security(vault):
    policy.POLICY_FILE.parent.mkdir(parents=True)
    policy.POLICY_FILE.write_text('not json')
    with pytest.raises(policy.MailboxPolicyError):
        policy.load_policy()


def test_symlink_attack_blocks_storage(vault, tmp_path):
    other = tmp_path / 'outside'
    other.mkdir()
    try:
        (vault / '.local_agent').symlink_to(other, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('Windows account cannot create a symlink without developer mode')
    with pytest.raises(policy.MailboxPolicyError):
        policy.save_policy(dict(enabled=True, allow_octava=True, allow_blender=True, allow_tests=True, allow_asset_sync=False))
    assert not list(other.iterdir())


def test_octava_calls_are_unlimited_by_local_daily_policy(vault):
    at = datetime(2026, 10, 11, tzinfo=timezone.utc)
    for _ in range(100):
        assert policy.reserve_octava_call(at) is None
    assert policy.reserve_octava_call(at + timedelta(days=1)) is None


def test_legacy_corrupt_counter_does_not_block_paid_calls(vault):
    legacy = vault / '.local_agent' / 'octava_call_limit.json'
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('not json')
    assert policy.reserve_octava_call() is None
    assert legacy.read_text() == 'not json'
