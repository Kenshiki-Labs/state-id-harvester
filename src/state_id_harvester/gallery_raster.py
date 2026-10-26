"""Header-first, pixel-budgeted raster validation; originals are never rewritten."""

from __future__ import annotations

import struct
import zlib
from typing import Any

import pymupdf

PNG = b"\x89PNG\r\n\x1a\n"
SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    position = 2
    header = data[:65536]
    while position + 4 <= len(header):
        if header[position] != 0xFF:
            raise ValueError("Invalid JPEG marker")
        marker = header[position + 1]
        position += 2
        if marker in {0xFF, 0x01} or 0xD0 <= marker <= 0xD8:
            continue
        length = int.from_bytes(header[position : position + 2], "big")
        if length < 2 or position + length > len(header):
            raise ValueError("JPEG header incomplete or exceeds header budget")
        if marker in SOF:
            if length < 8:
                raise ValueError("Invalid JPEG frame header")
            height, width = struct.unpack(">HH", header[position + 3 : position + 7])
            return width, height
        position += length
    raise ValueError("No JPEG dimensions within header budget")


def raster_header(data: bytes) -> tuple[str, int, int]:
    if data.startswith(PNG):
        if len(data) < 33 or data[8:16] != b"\0\0\0\rIHDR":
            raise ValueError("Invalid PNG header")
        if zlib.crc32(data[12:29]) != int.from_bytes(data[29:33], "big"):
            raise ValueError("PNG header checksum mismatch")
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height
    if data.startswith(b"\xff\xd8"):
        width, height = jpeg_dimensions(data)
        return "jpeg", width, height
    raise ValueError("Unsupported raster signature; only PNG/JPEG originals are accepted")


def validate_raster(data: bytes, content_type: str, max_pixels: int) -> dict[str, Any]:
    image_format, width, height = raster_header(data)
    media_type = content_type.partition(";")[0].strip().lower()
    allowed = {"application/octet-stream", "image/png" if image_format == "png" else "image/jpeg"}
    if media_type not in allowed:
        raise ValueError("Raster signature and Content-Type disagree")
    if min(width, height) < 1 or max(width, height) > 20000 or width * height > max_pixels:
        raise ValueError("Raster dimensions exceed pixel budget before decoding")
    try:
        pix = pymupdf.Pixmap(data)
    except Exception as exc:
        raise ValueError("Native raster decoder rejected source") from exc
    if pix.width != width or pix.height != height:
        raise ValueError("Decoded raster dimensions disagree with retained header")
    return {
        "format": image_format,
        "width": width,
        "height": height,
        "validation": "header_budget_then_native_decode; not credential qualification",
    }
