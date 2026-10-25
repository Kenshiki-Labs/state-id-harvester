"""Budgeted derivative writing; retained sources are never modified."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from .models import Asset

AssetKind = Literal[
    "extracted_image",
    "raw_stream",
    "page_render",
    "thumbnail",
    "text",
    "geometry",
    "card_candidate",
]


class ExtractionLimit(Exception):
    pass


def box(values: Any) -> tuple[float, float, float, float]:
    return float(values[0]), float(values[1]), float(values[2]), float(values[3])


def matrix(values: Any) -> tuple[float, float, float, float, float, float]:
    return (*box(values), float(values[4]), float(values[5]))


class AssetWriter:
    def __init__(self, staging: Path, target_relative: Path, byte_limit: int) -> None:
        self.staging = staging
        self.target_relative = target_relative
        self.byte_limit = byte_limit
        self.written_bytes = 0
        self.assets: list[Asset] = []

    def save(
        self,
        name: str,
        data: bytes,
        kind: AssetKind,
        page: int | None = None,
        xref: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> str:
        self.written_bytes += len(data)
        if self.written_bytes > self.byte_limit:
            raise ExtractionLimit("Extracted asset byte budget exceeded")
        path = self.staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        relative = (self.target_relative / name).as_posix()
        self.assets.append(
            Asset(
                path=relative,
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
                kind=kind,
                page_number=page,
                xref=xref,
                width=width,
                height=height,
            )
        )
        return relative

    def save_json(self, name: str, records: Any, kind: Literal["text", "geometry"]) -> str:
        data = (json.dumps(records, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
        return self.save(name, data, kind)
