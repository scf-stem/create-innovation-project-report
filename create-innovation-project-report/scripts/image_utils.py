#!/usr/bin/env python3
"""Read basic image metadata with the Python standard library only."""

from __future__ import annotations

import struct
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImageInfo:
    format: str
    mime_type: str
    extension: str
    width: int
    height: int
    dpi_x: float | None = None
    dpi_y: float | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["megapixels"] = round(self.width * self.height / 1_000_000, 2)
        return data


def _png_info(data: bytes) -> ImageInfo:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Invalid PNG image")
    width, height = struct.unpack(">II", data[16:24])
    dpi_x = dpi_y = None
    offset = 8
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        if chunk_type == b"pHYs" and len(chunk_data) >= 9 and chunk_data[8] == 1:
            pixels_x, pixels_y = struct.unpack(">II", chunk_data[:8])
            dpi_x = round(pixels_x * 0.0254, 2)
            dpi_y = round(pixels_y * 0.0254, 2)
        offset += 12 + length
        if chunk_type == b"IEND":
            break
    return ImageInfo("PNG", "image/png", ".png", width, height, dpi_x, dpi_y)


def _gif_info(data: bytes) -> ImageInfo:
    if len(data) < 10 or data[:6] not in (b"GIF87a", b"GIF89a"):
        raise ValueError("Invalid GIF image")
    width, height = struct.unpack("<HH", data[6:10])
    return ImageInfo("GIF", "image/gif", ".gif", width, height)


def _bmp_info(data: bytes) -> ImageInfo:
    if len(data) < 26 or data[:2] != b"BM":
        raise ValueError("Invalid BMP image")
    width, height = struct.unpack("<ii", data[18:26])
    return ImageInfo("BMP", "image/bmp", ".bmp", abs(width), abs(height))


def _jpeg_info(data: bytes) -> ImageInfo:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise ValueError("Invalid JPEG image")
    offset = 2
    width = height = None
    dpi_x = dpi_y = None
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while offset < len(data):
        while offset < len(data) and data[offset] != 0xFF:
            offset += 1
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            break
        segment_length = struct.unpack(">H", data[offset : offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(data):
            break
        payload = data[offset + 2 : offset + segment_length]
        if marker == 0xE0 and payload.startswith(b"JFIF\x00") and len(payload) >= 12:
            units = payload[7]
            density_x, density_y = struct.unpack(">HH", payload[8:12])
            if units == 1:
                dpi_x, dpi_y = float(density_x), float(density_y)
            elif units == 2:
                dpi_x = round(density_x * 2.54, 2)
                dpi_y = round(density_y * 2.54, 2)
        if marker in sof_markers and len(payload) >= 5:
            height, width = struct.unpack(">HH", payload[1:5])
            break
        offset += segment_length
    if not width or not height:
        raise ValueError("JPEG dimensions not found")
    return ImageInfo("JPEG", "image/jpeg", ".jpg", width, height, dpi_x, dpi_y)


def inspect_image(path: Path) -> ImageInfo:
    image_path = path.expanduser().resolve()
    with image_path.open("rb") as stream:
        data = stream.read()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return _png_info(data)
    if data.startswith(b"\xff\xd8"):
        return _jpeg_info(data)
    if data.startswith((b"GIF87a", b"GIF89a")):
        return _gif_info(data)
    if data.startswith(b"BM"):
        return _bmp_info(data)
    raise ValueError(f"Unsupported image format: {image_path}")
