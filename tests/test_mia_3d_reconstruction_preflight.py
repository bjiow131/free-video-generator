"""No downloads or untrusted code during local image-to-3D capability probe."""
import json
from types import SimpleNamespace
import hashlib
import pytest
from local_agent import poller
from local_agent.control_protocol import parse_task, ProtocolError


def task(args):
    return json.dumps({"protocol_version":1,"task_id":"mia-3d-preflight-test",
      "operation":"mia_3d_reconstruction_preflight",
      "created_at":"2026-10-13T01:00:00+00:00",
      "expires_at":"2026-10-13T01:25:00+00:00",
      "requires_local_approval":True, "arguments":args})


def test_reject_any_remote_override():
    assert parse_task(task({})).operation == "mia_3d_reconstruction_preflight"
    for bad in ({"script":"x"}, {"url":"https://example.net"}, {"command":"pip install"},
                {"model":"unknown"}):
        with pytest.raises(ProtocolError):
            parse_task(task(bad))


def test_no_changes_if_reference_missing(monkeypatch,tmp_path):
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    monkeypatch.setattr("local_agent.mailbox_policy.load_policy",lambda:{"allow_blender":True})
    assert poller._run_mia_3d_reconstruction_preflight({})["reason"] == "approved_mia_source_missing"


def test_fixed_approved_reference_and_gpu_network_probe(monkeypatch,tmp_path):
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    ref=tmp_path/"episode1/assets/references/mia_turnaround_approved_20261012.jpeg"
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"\xff\xd8\xff"+b"x"*100)
    monkeypatch.setattr("local_agent.mailbox_policy.load_policy",lambda:{"allow_blender":True})
    original_hash=hashlib.sha256
    class FakeDigest:
        def hexdigest(self):
            return "7a3194accfecdb4873bc7d4cd8015edb5a94075ca05c72013c5ad97b4a32e383"
    monkeypatch.setattr(hashlib,"sha256",lambda value=b"": FakeDigest())
    import shutil
    monkeypatch.setattr(shutil,"disk_usage",lambda path:SimpleNamespace(free=30*1024**3))
    monkeypatch.setattr(shutil,"which",lambda exe:"C:\\bin\\"+exe if exe in ("nvidia-smi","git") else None)
    monkeypatch.setattr(poller.subprocess,"run",lambda *args,**kwargs:SimpleNamespace(
      stdout="NVIDIA GeForce RTX 4060, 8188, 7100\n",returncode=0))
    import urllib.request
    class R:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):return False
    called=[]
    def fake_open(request,timeout):
        called.append(request.full_url)
        assert request.get_method()=="HEAD"
        return R()
    monkeypatch.setattr(urllib.request,"urlopen",fake_open)
    result=poller._run_mia_3d_reconstruction_preflight({})
    assert result["status"]=="completed"
    assert result["hardware"]["vram_mib"]==8188
    assert result["suitable_for_separate_venv_experiment"] is True
    assert result["downloads_performed"] is False
    assert result["source_verified"] is True
    assert len(called)==2
