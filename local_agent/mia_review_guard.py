"""Bounded, dependency-free duplicate detection for Mia front review renders.

This is an anti-spam signal, not a facial identity or 3-D geometry score.
Read-only; it does not run embedded Blender scripts or fetch external assets.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import zlib

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_PNG = 8_000_000
_MAX_SCANLINES = 48_000_000
_MAX_SEARCH = 24


def _png_scanlines(path: Path) -> tuple[tuple[int, ...], bytes] | None:
    """Return reconstructed pixel bytes (without metadata or PNG filters).

    Identical Blender frames may have different file metadata. Comparing IDAT
    content rather than whole-file bytes prevents that metadata defeating dedup.
    Invalid, oversized, or unsafe image files are never decompressed.
    """
    try:
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            return None
        size = path.stat().st_size
        if not 64 <= size <= _MAX_PNG:
            return None
        data = path.read_bytes()
        if not data.startswith(_PNG_SIGNATURE):
            return None
        offset = len(_PNG_SIGNATURE)
        dimensions = None
        chunks = []
        total_idat = 0
        for _ in range(256):
            if offset + 12 > len(data):
                return None
            length = struct.unpack_from(">I", data, offset)[0]
            name = data[offset + 4:offset + 8]
            end = offset + 12 + length
            if length > _MAX_PNG or end > len(data):
                return None
            payload = data[offset + 8:offset + 8 + length]
            offset = end
            if name == b"IHDR":
                if dimensions is not None or length != 13:
                    return None
                width, height, depth, color, comp, fltr, interlace = struct.unpack(">IIBBBBB", payload)
                if not (1 <= width <= 4096 and 1 <= height <= 4096):
                    return None
                if depth not in (8, 16) or color not in (0, 2, 4, 6) or comp or fltr or interlace:
                    return None
                channels = {0: 1, 2: 3, 4: 2, 6: 4}[color]
                uncompressed_size = height * (1 + width * channels * (depth // 8))
                if uncompressed_size > _MAX_SCANLINES:
                    return None
                dimensions = (width, height, depth, color)
            if name == b"IDAT":
                total_idat += length
                if total_idat > _MAX_PNG:
                    return None
                chunks.append(payload)
            if name == b"IEND":
                break
        if dimensions is None or not chunks:
            return None
        stream = zlib.decompressobj()
        image = stream.decompress(b"".join(chunks), _MAX_SCANLINES + 1)
        if stream.unconsumed_tail or not stream.eof:
            return None
        if len(image) != uncompressed_size:
            return None
        # PNG filters encode differences, not pixel values. Undo each row before
        # comparing: the same pixels can use different encoder/filter choices.
        stride = width * channels * (depth // 8)
        bpp = channels * (depth // 8)
        pixels = bytearray(height * stride)
        previous = bytearray(stride)
        for row in range(height):
            start = row * (stride + 1)
            kind = image[start]
            if kind > 4:
                return None
            current = bytearray(image[start + 1:start + 1 + stride])
            for i in range(stride):
                left = current[i - bpp] if i >= bpp else 0
                up = previous[i]
                diagonal = previous[i - bpp] if i >= bpp else 0
                if kind == 1:
                    predictor = left
                elif kind == 2:
                    predictor = up
                elif kind == 3:
                    predictor = (left + up) // 2
                elif kind == 4:
                    estimate = left + up - diagonal
                    da, db, dc = abs(estimate-left), abs(estimate-up), abs(estimate-diagonal)
                    predictor = left if da <= db and da <= dc else up if db <= dc else diagonal
                else:
                    predictor = 0
                current[i] = (current[i] + predictor) & 255
            pixels[row * stride:(row + 1) * stride] = current
            previous = current
        return dimensions, bytes(pixels)
    except (OSError, ValueError, struct.error, zlib.error, OverflowError):
        return None


def front_difference(first: Path, second: Path) -> dict[str, object] | None:
    """Normalized difference of bounded reconstructed pixel samples.

    The metric is deliberately conservative: it is only a repeated-render
    warning, not a perceptual similarity/identity approval.
    """
    a = _png_scanlines(first)
    b = _png_scanlines(second)
    if a is None or b is None or a[0] != b[0] or len(a[1]) != len(b[1]):
        return None
    if hashlib.sha256(a[1]).digest() == hashlib.sha256(b[1]).digest():
        return {"duplicate": True, "average_abs_byte_delta": 0.0,
                "reason": "identical_decoded_png"}
    step = max(1, len(a[1]) // 65_536)
    aa = a[1][::step]
    bb = b[1][::step]
    difference = sum(abs(x - y) for x, y in zip(aa, bb)) / len(aa)
    return {"duplicate": difference <= 0.8,
            "average_abs_byte_delta": round(difference, 4),
            "reason": "near_identical_png" if difference <= 0.8 else "different_png"}


def find_recent_duplicate(project: Path, review: Path) -> dict[str, object] | None:
    """Compare front with recent separate review jobs; never follow symlinks."""
    current = review / "front.png"
    if _png_scanlines(current) is None:
        return None
    try:
        previous = [
            p for p in project.iterdir()
            if p != review and p.is_dir() and not p.is_symlink()
            and not getattr(p, "is_junction", lambda: False)()
            and (p / "front.png").is_file()
            and (p / "front.png").stat().st_mtime <= current.stat().st_mtime
        ]
        previous.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for old in previous[:_MAX_SEARCH]:
            value = front_difference(current, old / "front.png")
            if value is not None and value["duplicate"]:
                return {"matched_review": old.name, **value}
    except OSError:
        return None
    return None
