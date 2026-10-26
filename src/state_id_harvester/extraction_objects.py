"""Preserve native PDF content/Form streams and embedded font programs unchanged.

The retained source PDF is authoritative. These source-local derivative objects
support component inspection; no claim of a complete editable reconstruction.
"""

from __future__ import annotations

from typing import Any

from .extraction_assets import AssetWriter
from .pdf_objects import PageObjectInventory


class NativeObjectStreams:
    def __init__(self, doc: Any, writer: AssetWriter) -> None:
        self.doc = doc
        self.writer = writer
        self.saved: dict[int, dict[str, str]] = {}

    def preserve(self, inventory: PageObjectInventory) -> list[dict[str, str]]:
        records = []
        for obj in inventory.objects:
            if obj.kind not in {"content_stream", "form", "font"}:
                continue
            if obj.xref not in self.saved:
                self.saved[obj.xref] = self._save(obj.xref, obj.kind, inventory.page_number)
            records.append({"object_id": obj.object_id, **self.saved[obj.xref]})
        return records

    def _save(self, xref: int, kind: str, number: int) -> dict[str, str]:
        paths = {}
        if self.doc.xref_is_stream(xref):
            raw = self.doc.xref_stream_raw(xref)
            paths["raw_stream_path"] = self.writer.save(
                f"native_objects/xref{xref}.stream", raw, "raw_stream", number, xref
            )
        if kind == "font":
            _, extension, _, program = self.doc.extract_font(xref)
            if program:
                # Extension is constrained rather than interpolating a PDF font name.
                suffix = extension if extension in {"ttf", "otf", "cff", "pfa", "cid"} else "bin"
                paths["font_program_path"] = self.writer.save(
                    f"native_objects/font{xref}.{suffix}", program, "raw_stream", number, xref
                )
        return paths
