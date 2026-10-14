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


def test_each_completed_mia_visual_operation_attaches_front_delivery(monkeypatch):
    sent=[]
    monkeypatch.setattr(studio,"telegram_send_mia_front_thumbnail",
                        lambda task_id, image: sent.append((task_id,image)) or {"status":"delivered","sent":["front"]})
    details={"status":"completed","thumbnail_jpeg_base64":{"front":"jpeg-data","back":"ignored"}}
    poller._attach_mia_front_photo_delivery("blender_mia_source_adapt","run-42",details)
    assert sent==[("run-42","jpeg-data")]
    assert details["telegram_photo_delivery"]=={"status":"delivered","sent":["front"]}
    # Re-processing the same result cannot send a second copy.
    poller._attach_mia_front_photo_delivery("blender_mia_source_adapt","run-42",details)
    assert len(sent)==1


def test_failed_mia_visual_run_does_not_claim_or_send_a_photo(monkeypatch):
    sent=[]
    monkeypatch.setattr(studio,"telegram_send_mia_front_thumbnail",
                        lambda *args: sent.append(args) or {"status":"delivered"})
    details={"status":"failed","thumbnail_jpeg_base64":{"front":"jpeg-data"}}
    poller._attach_mia_front_photo_delivery("mia_model_review","run-43",details)
    assert sent==[]
    assert "telegram_photo_delivery" not in details


def test_photo_delivery_publishes_only_static_front_png_to_only_paired_chat(monkeypatch,tmp_path):
    folder=tmp_path/"MIA_REFERENCE_REVIEW"/"review1"
    folder.mkdir(parents=True)
    for name in ("front","three_quarter","side","back"):
        (folder/(name+".png")).write_bytes(b"\x89PNG\r\n\x1a\n"+b"image"+b"Z"*80)
    token="123456:"+"A"*32
    monkeypatch.setattr(studio,"_telegram_credentials",lambda:(token,"12345"))
    monkeypatch.setattr(studio,"telegram_notifications_enabled",lambda:True)
    monkeypatch.setattr(studio,"telegram_transport_settings",lambda:{"use_relay":False})
    recorded=[]
    def send(received_token, method, data, *, timeout=10):
        assert received_token == token
        assert method == "sendPhoto"
        assert data["chat_id"] == "12345"
        assert data["filename"] == "front.png"
        import base64
        assert base64.b64decode(data["photo_base64"]).startswith(b"\x89PNG\r\n\x1a\n")
        recorded.append(data["filename"])
        return {"ok": True}
    monkeypatch.setattr(studio,"_telegram_call",send)
    result=studio.telegram_send_mia_review_photos(tmp_path,"review1")
    assert result["status"]=="delivered"
    assert result["sent"]==["front"]
    assert recorded==["front.png"]
    assert len(list(folder.glob("*.png")))==4  # other local views remain untouched


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
    assert result["failed"]==["front"]
    assert len(list(folder.glob("*.png")))==4
