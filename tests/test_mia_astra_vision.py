"""Astra visual review must only process the preapproved local source and renders."""
from __future__ import annotations

import io
import json
import hashlib
from pathlib import Path
from urllib import request
from local_agent import poller
from local_agent.control_protocol import parse_task, ProtocolError
import pytest


def _envelope(operation, arguments):
    return json.dumps({
        "protocol_version":1,"task_id":"test-astravision-01","operation":operation,
        "created_at":"2026-10-13T00:00:00+00:00",
        "expires_at":"2026-10-13T00:20:00+00:00",
        "requires_local_approval":True,"arguments":arguments})


def test_protocol_is_strict_fixed_job():
    assert parse_task(_envelope("mia_astra_review", {})).operation=="mia_astra_review"
    for args in ({"url":"https://elsewhere"},{"path":"../secret"},{"script":"evil"},{"model":"other"}):
        with pytest.raises(ProtocolError):
            parse_task(_envelope("mia_astra_review",args))


def _policy():
    return {"enabled":True,"allow_octava":True,"allow_blender":True,
            "allow_tests":False,"allow_asset_sync":False}


def test_absent_reference_stops_before_api(monkeypatch,tmp_path):
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    monkeypatch.setattr("local_agent.mailbox_policy.load_policy",_policy)
    assert poller._run_mia_astra_review({})["reason"]=="canonical_source_or_review_not_found"


def test_disabled_provider_permission_fails_closed(monkeypatch,tmp_path):
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    policy=_policy()
    policy["allow_octava"]=False
    monkeypatch.setattr("local_agent.mailbox_policy.load_policy",lambda:policy)
    assert poller._run_mia_astra_review({})["reason"]=="local_blender_and_octava_permissions_required"


def test_six_actual_local_images_in_astra_request(monkeypatch,tmp_path):
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    monkeypatch.setattr("local_agent.mailbox_policy.load_policy",_policy)
    approved=tmp_path/"episode1/assets/references/mia_turnaround_approved_20261012.jpeg"
    approved.parent.mkdir(parents=True)
    approved.write_bytes(b"\xff\xd8\xff"+b"j"*111598)
    folder=tmp_path/"MIA_REFERENCE_REVIEW/mia-static-model-v6-20261012T222818971Z"
    folder.mkdir(parents=True)
    (folder/"mia_reference_model.blend").write_bytes(b"B"*1001)
    for name in ("front","three_quarter","side","back"):
        (folder/(name+".png")).write_bytes(b"\x89PNG\r\n\x1a\n"+b"p"*1000)
    (folder/"face_thumb.jpg").write_bytes(b"\xff\xd8\xff"+b"f"*100)
    import local_agent.octava_credentials as creds
    monkeypatch.setattr(creds,"read_key",lambda:("REDACTED","windows_vault"))
    # This fixture mocks ONLY SHA verification, rather than needing to commit
    # the user's private image to the code repository.
    original_sha=hashlib.sha256
    expected="7a3194accfecdb4873bc7d4cd8015edb5a94075ca05c72013c5ad97b4a32e383"
    class FakeHash:
        def hexdigest(self):return expected
    monkeypatch.setattr(hashlib,"sha256",lambda data=b"":FakeHash())
    sent=[]
    class FakeResponse:
        def __enter__(self):return self
        def __exit__(self,*args):return None
        def read(self,n):
            return json.dumps({"choices":[{"message":{"content":"I SEE BOTH IMAGES. REJECT: eyes too large; correct mesh width."}}]}).encode()
    def fake_send(req,timeout):
        assert req.full_url=="https://octavapi.shop/v1/chat/completions"
        assert timeout==100
        assert req.get_header("Authorization")=="Bearer REDACTED"
        body=json.loads(req.data)
        assert body["model"]=="gpt-6-astra"
        assert "IDENTITY PRESERVATION CONTRACT" in body["messages"][0]["content"]
        blocks=body["messages"][1]["content"]
        images=[v for v in blocks if v["type"]=="image_url"]
        assert len(images)==6
        assert images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert images[1]["image_url"]["url"].startswith("data:image/png;base64,")
        sent.append(body)
        return FakeResponse()
    monkeypatch.setattr(request,"urlopen",fake_send)
    result=poller._run_mia_astra_review({})
    assert result["status"]=="completed"
    assert result["vision_images_sent"]==6
    assert result["model_requested"]=="gpt-6-astra"
    assert result["geometry_changed"] is False
    assert "REJECT" in (folder/"astra_identity_review.txt").read_text()
    assert len(sent)==1


def test_no_repeat_execution_can_overwrite_feedback(monkeypatch,tmp_path):
    monkeypatch.setenv("LOCAL_AGENT_WORKSPACE",str(tmp_path))
    assert poller._run_mia_astra_review({"script":"do-anything"})["status"]=="rejected"
