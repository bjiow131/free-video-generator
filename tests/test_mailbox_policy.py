"""Offline unattended mailbox authorization + durable spending limit tests."""
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
    monkeypatch.setattr(policy, '_CALLS_FILE', root / '.local_agent' / 'octava_call_limit.json')
    return root


def test_default_is_disabled_and_safest(vault):
    assert policy.load_policy() == policy.default_policy()
    assert not policy.is_auto_authorized('doctor')
    assert not policy.is_auto_authorized('octava_advice')


def test_local_enable_accepts_diagnostics_and_never_arbitrary_patch(vault):
    value = dict(enabled=True, allow_octava=False, allow_blender=False, allow_tests=False)
    assert policy.save_policy(value) == value
    assert policy.load_policy() == value
    for op in policy.READ_ONLY_OPERATIONS:
        assert policy.is_auto_authorized(op)
    for op in ('apply_patch', 'start', 'stop', 'backup', 'logs', 'blender_open_mia_project', 'run_script'):
        assert not policy.is_auto_authorized(op)
    assert not policy.is_auto_authorized('octava_advice')
    assert not policy.is_auto_authorized('blender_mia_skeleton')


def test_optional_permissions_are_independent(vault):
    value = dict(enabled=True, allow_octava=True, allow_blender=True, allow_tests=True)
    policy.save_policy(value)
    assert policy.is_auto_authorized('octava_advice')
    assert policy.is_auto_authorized('test')
    assert policy.is_auto_authorized('save_story_plan')
    assert not policy.is_auto_authorized('apply_patch')
    value['enabled'] = False
    policy.save_policy(value)
    assert not policy.is_auto_authorized('octava_advice')


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
    (vault / '.local_agent').symlink_to(other, target_is_directory=True)
    with pytest.raises(policy.MailboxPolicyError):
        policy.save_policy(dict(enabled=True, allow_octava=True, allow_blender=True, allow_tests=True))
    assert not list(other.iterdir())


def test_daily_octava_budget_survives_restart(vault):
    at = datetime(2026, 10, 11, tzinfo=timezone.utc)
    for n in range(1, policy.MAX_OCTAVA_CALLS_PER_UTC_DAY + 1):
        assert policy.reserve_octava_call(at) == n
    with pytest.raises(policy.MailboxPolicyError, match='лимит'):
        policy.reserve_octava_call(at)
    assert policy.reserve_octava_call(at + timedelta(days=1)) == 1


def test_corrupt_budget_blocks_request(vault):
    policy._CALLS_FILE.parent.mkdir(parents=True)
    policy._CALLS_FILE.write_text('{"day":"2026-10-11", "calls": "unlimited"}')
    with pytest.raises(policy.MailboxPolicyError):
        policy.reserve_octava_call(datetime(2026, 10, 11, tzinfo=timezone.utc))