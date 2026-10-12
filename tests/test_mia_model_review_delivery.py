"""Mia model review: only fixed local meshes/stills; no remote arbitrary file requests."""
from __future__ import annotations
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from local_agent import studio_server as studio, poller
from local_agent.control_protocol import parse_task, ProtocolError
from local_agent.mailbox_policy import is_auto_authorized


def envelope(arguments, operation="mia_model_review"):
    return json.dumps({
       "protocol_version":1, "task_id":"mia-review-test", "operation":operation,
       "created_at":"2026-10-13T00:00:00+00:00",
       "expires_at":"2026-10-13T00:25:00+00:00",
       "requires_local_approval":True, "arguments":arguments,
    })


def test_review_operation_accepts_no_arbitrary_remote_inputs():
    assert parse_task(envelope({})).operation=="mia_model_review"
    for arguments in ({"project_name":"episode1"},{"script":"print(1)"},{"prompt":"make video"},{"url":"https://example.org"},{"images":["x"]}):
        with pytest.raises(ProtocolError):
            parse_task(envelope(arguments))
    assert is_auto_authorized("mia_model_review",{
        "enabled":True,"allow_blender":True,"allow_tests":False,
        "allow_octava":False,"allow_asset_sync":False
    })
    assert not is_auto_authorized("mia_model_review",{
        "enabled":True,"allow_blender":False,"allow_tests":False,
        "allow_octava":True,"allow_asset_sync":False
    })


def test_photo_delivery_publishes_four_static_pngs_to_only_paired_chat(monkeypatch,tmp_path):
    folder=tmp_path/"MIA_REFERENCE_REVIEW"/"review1"
    folder.mkdir(parents=True)
    for name in ("front","three_quarter","side","back"):
        (folder/(name+".png")).write_bytes(b"\x89PNG\r\n\x1a\n"+b"image"+b"Z"*80)
    token="123456:"+"A"*32
    monkeypatch.setattr(studio,"_telegram_credentials",lambda:(token,"12345"))
    monkeypatch.setattr(studio,"telegram_notifications_enabled",lambda:True)
    monkeypatch.setattr(studio,"telegram_transport_settings",lambda:{"use_relay":False})
    recorded=[]
    def post(url,**kwargs):
        assert url=="https://api.telegram.org/bot"+token+"/sendPhoto"
        assert kwargs["data"]["chat_id"]=="12345"
        assert kwargs["files"]["photo"][1].read(8)==b"\x89PNG\r\n\x1a\n"
        recorded.append(kwargs["files"]["photo"][0])
        return SimpleNamespace(status_code=200,headers={"Content-Type":"application/json"},
                               json=lambda:{"ok":True})
    import requests
    monkeypatch.setattr(requests,"post",post)
    result=studio.telegram_send_mia_review_photos(tmp_path,"review1")
    assert result["status"]=="delivered"
    assert len(result["sent"])==4
    assert recorded==["front.png","three_quarter.png","side.png","back.png"]
    assert len(list(folder.glob("*.png")))==4  # originals survive upload


def test_refuse_wrong_path_symlink_and_disabled_notifications(monkeypatch,tmp_path):
    monkeypatch.setattr(studio,"_telegram_credentials",lambda:("123456:"+"A"*32,"12345"))
    monkeypatch.setattr(studio,"telegram_notifications_enabled",lambda:True)
    assert studio.telegram_send_mia_review_photos(tmp_path,"../evil")["status"]=="blocked"
    assert studio.telegram_send_mia_review_photos(tmp_path,"missing")["status"]=="blocked"
    monkeypatch.setattr(studio,"telegram_notifications_enabled",lambda:False)
    assert studio.telegram_send_mia_review_photos(tmp_path,"review1")["status"]=="disabled_in_local_studio"


def test_one_bad_photo_does_not_send_arbitrary_file_or_erase_good_photos(monkeypatch,tmp_path):
    folder=tmp_path/"MIA_REFERENCE_REVIEW"/"review2"
    folder.mkdir(parents=True)
    for name in ("front","three_quarter","side","back"):
        (folder/(name+".png")).write_bytes(b"bad"+b"Y"*80)
    monkeypatch.setattr(studio,"_telegram_credentials",lambda:("123456:"+"A"*32,"12345"))
    monkeypatch.setattr(studio,"telegram_notifications_enabled",lambda:True)
    monkeypatch.setattr(studio,"telegram_transport_settings",lambda:{"use_relay":False})
    import requests
    monkeypatch.setattr(requests,"post",lambda *a,**kw: (_ for _ in ()).throw(AssertionError("Do not upload untrusted media")))
    result=studio.telegram_send_mia_review_photos(tmp_path,"review2")
    assert result["status"]=="failed"
    assert result["sent"]==[]
    assert len(result["failed"])==4
    assert len(list(folder.glob("*.png")))==4
