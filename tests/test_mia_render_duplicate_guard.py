"""Regression tests: never deliver dozens of identical Mia frames to Telegram."""
from __future__ import annotations

import binascii
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace

from local_agent.mia_review_guard import (
    _png_scanlines, find_recent_duplicate, front_difference,
)
from local_agent import studio_server as studio


def png(color: tuple[int, int, int], *, note: bytes = b"") -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF))
    # Deliberately fixed real RGB PNG pixels; optional different metadata.
    width, height = 32, 32
    raw = b"".join(b"\x00" + bytes(color) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            (chunk(b"tEXt", b"run\x00" + note) if note else b"") +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_review(root: Path, name: str, color: tuple[int, int, int],
                metadata: bytes = b"") -> Path:
    folder = root / "MIA_REFERENCE_REVIEW" / name
    folder.mkdir(parents=True)
    for view in ("front", "three_quarter", "side", "back"):
        (folder / (view + ".png")).write_bytes(png(color, note=metadata))
    return folder


def test_png_metadata_does_not_hide_identical_render(tmp_path):
    a, b, c = [tmp_path / n for n in ("one.png", "two.png", "three.png")]
    a.write_bytes(png((50, 130, 200), note=b"first-render"))
    b.write_bytes(png((50, 130, 200), note=b"second-render"))
    c.write_bytes(png((220, 30, 20)))
    assert a.read_bytes() != b.read_bytes()
    assert _png_scanlines(a) is not None
    assert front_difference(a, b)["reason"] == "identical_decoded_png"
    assert front_difference(a, b)["duplicate"] is True
    assert front_difference(a, c)["duplicate"] is False


def test_invalid_or_oversized_png_is_not_treated_as_duplicate(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"broken" * 50)
    b.write_bytes(png((1, 2, 3)))
    assert front_difference(a, b) is None


def test_find_duplicate_for_separate_review_jobs(tmp_path):
    prior = make_review(tmp_path, "review_1", (100, 45, 30), b"old")
    current = make_review(tmp_path, "review_2", (100, 45, 30), b"new")
    match = find_recent_duplicate(tmp_path / "MIA_REFERENCE_REVIEW", current)
    assert match is not None
    assert match["matched_review"] == prior.name
    assert match["duplicate"] is True


def test_telegram_sends_front_for_each_new_review_but_deduplicates_task_id(monkeypatch, tmp_path):
    original = make_review(tmp_path, "model_first", (90, 80, 70), b"initial")

    monkeypatch.setattr(studio, "_telegram_credentials",
                        lambda: ("123456:" + "A" * 32, "12345"))
    monkeypatch.setattr(studio, "telegram_notifications_enabled", lambda: True)
    monkeypatch.setattr(studio, "telegram_transport_settings",
                        lambda: {"use_relay": False})
    posted = []
    def send(token, method, data, *, timeout=10):
        posted.append(data["filename"])
        return {"ok": True}
    monkeypatch.setattr(studio, "_telegram_call", send)
    result = studio.telegram_send_mia_review_photos(tmp_path, "model_first")
    assert result["status"] == "delivered"
    assert posted == ["front.png"]
    repeat = make_review(tmp_path, "model_again", (90, 80, 70), b"rerender")
    result2 = studio.telegram_send_mia_review_photos(tmp_path, "model_again")
    assert result2["status"] == "delivered"
    assert posted == ["front.png", "front.png"]
    assert studio.telegram_send_mia_review_photos(tmp_path, "model_first")["status"] == "already_delivered"
    assert (original / "front.png").is_file()
    assert (repeat / "front.png").is_file()


def test_identical_pixels_with_different_png_filters(tmp_path):
    from PIL import Image
    a, b = tmp_path / "raw.png", tmp_path / "filtered.png"
    a.write_bytes(png((50, 130, 200)))
    Image.new("RGB", (32, 32), (50, 130, 200)).save(b)
    assert front_difference(a, b)["duplicate"] is True
    assert studio.front_difference(a, b)["duplicate"] is True


def test_newer_unreviewed_render_does_not_suppress_first(tmp_path):
    import os
    first = make_review(tmp_path, "first", (90, 80, 70))
    later = make_review(tmp_path, "later", (90, 80, 70))
    os.utime(first / "front.png", (100, 100))
    os.utime(later / "front.png", (200, 200))
    assert find_recent_duplicate(first.parent, first) is None
    assert studio.find_recent_duplicate(first.parent, first) is None
    assert find_recent_duplicate(first.parent, later)["matched_review"] == "first"


def test_partial_front_delivery_retries_and_records_only_front(monkeypatch, tmp_path):
    import json
    folder = make_review(tmp_path, "partial", (80, 90, 70))
    monkeypatch.setattr(studio, "_telegram_credentials", lambda: ("123:" + "A"*32, "123"))
    monkeypatch.setattr(studio, "telegram_notifications_enabled", lambda: True)
    monkeypatch.setattr(studio, "telegram_transport_settings", lambda: {"use_relay":False})
    calls = []
    def send(token, method, data, *, timeout=10):
        calls.append(data["filename"])
        if len(calls) == 1:
            raise studio.TelegramAlertError("simulated delivery failure")
        return {"ok": True}
    monkeypatch.setattr(studio, "_telegram_call", send)
    assert studio.telegram_send_mia_review_photos(tmp_path,"partial")["status"] == "failed"
    assert studio.telegram_send_mia_review_photos(tmp_path,"partial")["status"] == "delivered"
    assert calls == ["front.png", "front.png"]
    receipt=json.loads((folder/".telegram_delivery.json").read_text())
    assert set(receipt["views_sent"])=={"front"}
