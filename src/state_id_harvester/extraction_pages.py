"""Bounded PDF image preservation and display-coordinate rendering."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import pymupdf

from .extraction_assets import AssetWriter, box, matrix
from .models import ImageGeometry, Options, Placement


class NativeImages:
    """Keep stream identity distinct from every on-page placement of that stream."""

    def __init__(
        self, doc: Any, options: Options, writer: AssetWriter, warnings: list[str]
    ) -> None:
        self.doc = doc
        self.options = options
        self.writer = writer
        self.warnings = warnings
        self.extracted: dict[int, tuple[str, str | None, str | None]] = {}

    def read(self, page: Any, number: int) -> list[ImageGeometry]:
        images: list[ImageGeometry] = []
        seen: set[int] = set()
        for entry in page.get_images(full=True):
            xref, smask, width, height = entry[:4]
            # Preservation is independent of credential classification. Small cards,
            # logos and decorative images all retain their native source evidence.
            if xref in seen or width <= 0 or height <= 0:
                continue
            seen.add(xref)
            if width * height > self.options.max_image_pixels:
                self.warnings.append(f"p{number} xref{xref}: image pixel limit exceeded")
                continue
            placements = [
                Placement(bbox=box(rect), transform=matrix(transform))
                for rect, transform in page.get_image_rects(xref, transform=True)
            ]
            if not placements:
                continue
            saved = self._streams(xref, smask, width, height, number)
            if saved is None:
                continue
            raw_path, extracted_path, mask_path = saved
            images.append(
                ImageGeometry(
                    xref=xref,
                    smask_xref=smask,
                    width=width,
                    height=height,
                    colorspace=str(entry[5]),
                    pdf_object=self.doc.xref_object(xref, compressed=False),
                    raw_stream_path=raw_path,
                    extracted_path=extracted_path,
                    smask_stream_path=mask_path,
                    placements=placements,
                )
            )
        return images

    def _streams(
        self, xref: int, smask: int, width: int, height: int, number: int
    ) -> tuple[str, str | None, str | None] | None:
        if xref in self.extracted:
            return self.extracted[xref]
        raw = self.doc.xref_stream_raw(xref)
        if raw is None:
            self.warnings.append(f"p{number} xref{xref}: no raw stream")
            return None
        raw_path = self.writer.save(
            f"native_xrefs/xref{xref}.stream",
            raw,
            "raw_stream",
            number,
            xref,
            width,
            height,
        )
        mask_path = self._mask(smask, xref, number)
        extracted_path = None
        image = self.doc.extract_image(xref)
        if image:
            ext = re.sub(r"[^a-z0-9]", "", image["ext"].lower()) or "bin"
            extracted_path = self.writer.save(
                f"native_xrefs/xref{xref}_{width}x{height}.{ext}",
                image["image"],
                "extracted_image",
                number,
                xref,
                width,
                height,
            )
        self.extracted[xref] = raw_path, extracted_path, mask_path
        return self.extracted[xref]

    def _mask(self, smask: int, xref: int, number: int) -> str | None:
        if not smask:
            return None
        mask = self.doc.xref_stream_raw(smask)
        if mask is None:
            return None
        return self.writer.save(
            f"native_xrefs/xref{xref}_smask{smask}.stream",
            mask,
            "raw_stream",
            number,
            smask,
        )


@dataclass
class RenderResult:
    rendered: bool = False
    skip_reason: str | None = None
    tiles: list[dict[str, object]] = field(default_factory=list)


class PageRenderer:
    def __init__(self, options: Options, writer: AssetWriter) -> None:
        self.options = options
        self.writer = writer

    def render(self, page: Any, number: int, selected: bool, has_slot: bool) -> RenderResult:
        if not selected:
            return RenderResult(skip_reason="No text feature or placed native image")
        if not has_slot:
            return RenderResult(skip_reason="Per-document render page budget")
        pixels = math.ceil(page.rect.width * self.options.dpi / 72) * math.ceil(
            page.rect.height * self.options.dpi / 72
        )
        result = RenderResult(rendered=True)
        if pixels > self.options.max_pixels:
            result = self._tiled(page, number)
        else:
            pix = page.get_pixmap(
                dpi=self.options.dpi,
                colorspace=pymupdf.csRGB,
                alpha=False,
                annots=True,
            )
            self._plate(pix, f"p{number}.png", number)
        if result.rendered:
            self._thumbnail(page, number)
        return result

    def _tiled(self, page: Any, number: int) -> RenderResult:
        edge = int(math.sqrt(self.options.max_pixels))
        scale = self.options.dpi / 72
        span = max(1, edge - 2) / scale
        cols, rows = math.ceil(page.rect.width / span), math.ceil(page.rect.height / span)
        if cols * rows > self.options.max_tiles_per_page:
            return RenderResult(skip_reason="Page pixel budget")
        tiles: list[dict[str, object]] = []
        for row in range(rows):
            for col in range(cols):
                rect = page.rect
                clip = pymupdf.Rect(
                    rect.x0 + col * span,
                    rect.y0 + row * span,
                    min(rect.x1, rect.x0 + (col + 1) * span),
                    min(rect.y1, rect.y0 + (row + 1) * span),
                )
                pix = page.get_pixmap(
                    dpi=self.options.dpi,
                    clip=clip,
                    colorspace=pymupdf.csRGB,
                    alpha=False,
                )
                path = self._plate(pix, f"p{number}_r{row}c{col}.png", number)
                tiles.append(
                    {
                        "path": path,
                        "display_clip": box(clip),
                        "pixel_origin": [pix.x, pix.y],
                        "dpi": self.options.dpi,
                    }
                )
        return RenderResult(rendered=True, tiles=tiles)

    def _plate(self, pix: Any, filename: str, number: int) -> str:
        return self.writer.save(
            f"pages_{self.options.dpi}dpi/{filename}",
            pix.tobytes("png"),
            "page_render",
            number,
            width=pix.width,
            height=pix.height,
        )

    def _thumbnail(self, page: Any, number: int) -> None:
        scale = min(0.75, math.sqrt(1_000_000 / max(page.rect.get_area(), 1)))
        thumb = page.get_pixmap(
            matrix=pymupdf.Matrix(scale, scale),
            colorspace=pymupdf.csRGB,
            alpha=False,
        )
        self.writer.save(
            f"thumbnails/p{number}.png",
            thumb.tobytes("png"),
            "thumbnail",
            number,
            width=thumb.width,
            height=thumb.height,
        )
