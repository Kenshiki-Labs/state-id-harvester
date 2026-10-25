"""Loss-aware PDF extraction, executed in isolated worker processes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Literal

import pymupdf

from . import __version__
from .extraction_assets import AssetWriter, box, matrix
from .extraction_assets import ExtractionLimit as ExtractionLimit
from .extraction_pages import NativeImages, PageRenderer
from .extraction_text import features as features
from .models import BoundaryCandidate, Document, Download, Options, PageGeometry, TextBlock
from .ocr import ocr_page
from .storage import atomic_json, within
from .topology import detect


def fingerprint(options: Options) -> str:
    data = options.model_dump(exclude={"refresh", "workers", "crawl_pages", "max_pdfs_per_state"})
    data.update(extractor=__version__, pymupdf=pymupdf.VersionBind)
    # Every extraction helper participates; moving implementation into a new module
    # cannot silently reuse a receipt from the old implementation.
    module_root = Path(__file__).parent
    modules = sorted(module_root.glob("extract*.py")) + [
        module_root / name for name in ("topology.py", "models.py", "ocr.py")
    ]
    data["implementation"] = hashlib.sha256(
        b"".join(path.name.encode() + b"\0" + path.read_bytes() for path in modules)
    ).hexdigest()
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def validate_pdf(doc: Any, options: Options) -> None:
    if doc.needs_pass:
        raise ExtractionLimit("Encrypted PDF requires a password")
    if doc.page_count > options.max_pages:
        raise ExtractionLimit(f"PDF has {doc.page_count} pages; limit is {options.max_pages}")
    if not doc.is_pdf or doc.page_count == 0:
        raise ExtractionLimit("Not a nonempty PDF")


class DocumentExtractor:
    """Per-document state; coordinate conventions remain explicit at each boundary."""

    def __init__(self, doc: Any, download: Download, options: Options, writer: AssetWriter) -> None:
        self.doc = doc
        self.download = download
        self.options = options
        self.normalize_id1 = (
            download.source.credential_format == "ID1"
            and download.source.discovery_jurisdiction != "US_FED"
        )
        self.writer = writer
        self.warnings: list[str] = []
        self.page_texts: list[str] = [page.get_text("text") for page in doc]
        self.per_page = [features(text) for text in self.page_texts]
        self.all_blocks: list[TextBlock] = []
        self.geometry: list[PageGeometry] = []
        self.boundaries: list[BoundaryCandidate] = []
        self.feature_evidence: list[dict[str, Any]] = []
        self.tables: list[dict[str, Any]] = []
        self.images = NativeImages(doc, options, writer, self.warnings)
        self.renderer = PageRenderer(options, writer)
        ranked = sorted(range(doc.page_count), key=lambda n: (-self._page_score(n), n))
        self.render_slots = set(ranked[: options.max_render_pages])

    def _page_score(self, number: int) -> int:
        headings = len(
            re.findall(
                r"security features|counterfeit|new card|card design",
                self.page_texts[number],
                re.I,
            )
        )
        return (
            len(self.per_page[number]) * 10
            + headings * 20
            + min(
                len(self.doc[number].get_images()),
                5,
            )
        )

    def run(self) -> Document:
        if not any(text.strip() for text in self.page_texts):
            self.warnings.append("No extractable text; OCR/manual review required")
        if not self.normalize_id1:
            self.warnings.append("Credential format unclassified; ID-1 normalization disabled")
        for index, page in enumerate(self.doc):
            self._page(page, index)
        self._save_records()
        return self._document()

    def _page(self, page: Any, index: int) -> None:
        number = index + 1
        blocks = [
            TextBlock(page_number=number, bbox=box(block), text=block[4])
            for block in page.get_text("blocks")
            if block[6] == 0 and block[4].strip()
        ]
        self._ocr(page, index, blocks)
        self.all_blocks.extend(blocks)
        self._record_features(blocks)
        images = self.images.read(page, number)
        selected = bool(self.per_page[index] or images or not any(self.page_texts))
        rendered = self.renderer.render(page, number, selected, index in self.render_slots)
        rotation = page.rotation
        rotation_matrix = matrix(page.rotation_matrix)
        pdf_to_mupdf = matrix(page.transformation_matrix)
        if self.options.detect_boundaries and index in self.render_slots and selected:
            self._topology(page, index, blocks)
        self.geometry.append(
            PageGeometry(
                page_number=number,
                mediabox=box(page.mediabox),
                cropbox=box(page.cropbox),
                rotation=rotation,
                rotation_matrix=rotation_matrix,
                pdf_to_mupdf_matrix=pdf_to_mupdf,
                matched_features=self.per_page[index],
                images=images,
                rendered=rendered.rendered,
                render_tiles=rendered.tiles,
                render_skip_reason=rendered.skip_reason,
            )
        )

    def _ocr(self, page: Any, index: int, blocks: list[TextBlock]) -> None:
        if not (self.options.ocr and index in self.render_slots and page.get_images()):
            return
        number = index + 1
        rotation = page.rotation
        try:
            page.set_rotation(0)
            ocr_blocks, tsv = ocr_page(page, number)
            blocks.extend(ocr_blocks)
            self.writer.save(f"text_blocks/p{number}_ocr.tsv", tsv, "text", number)
            self.per_page[index] = sorted(
                set(self.per_page[index]) | set(features(" ".join(b.text for b in ocr_blocks)))
            )
        except Exception as exc:
            self.warnings.append(f"p{number}: local OCR failed: {type(exc).__name__}")
        finally:
            page.set_rotation(rotation)

    def _record_features(self, blocks: list[TextBlock]) -> None:
        for block in blocks:
            categories = features(block.text)
            if categories:
                self.feature_evidence.append(
                    {
                        "page_number": block.page_number,
                        "bbox": block.bbox,
                        "text": block.text,
                        "method": block.method,
                        "feature_categories": categories,
                        "interpretation": "source_text_observation; not an approved runtime rule",
                    }
                )

    def _topology(self, page: Any, index: int, blocks: list[TextBlock]) -> None:
        rotation = page.rotation
        try:
            # OCR, tables, and candidates use unrotated source page coordinates;
            # display plates retain rotation, including their tile origins.
            page.set_rotation(0)
            if self.per_page[index]:
                self._tables(page, index + 1)
            if not self.normalize_id1:
                return
            for candidate, png in detect(page, blocks, index + 1):
                path = self.writer.save(
                    f"card_candidates/{candidate.candidate_id}.png",
                    png,
                    "card_candidate",
                    index + 1,
                )
                self.boundaries.append(candidate.model_copy(update={"crop_path": path}))
        finally:
            page.set_rotation(rotation)

    def _tables(self, page: Any, number: int) -> None:
        try:
            finder = page.find_tables()
            for table in finder.tables[:20]:
                self.tables.append(
                    {
                        "page_number": number,
                        "bbox": box(table.bbox),
                        "cells": [box(cell) if cell else None for cell in table.cells],
                        "rows": table.extract(),
                    }
                )
        except Exception as exc:
            self.warnings.append(f"p{number}: table extraction {type(exc).__name__}")

    def _save_records(self) -> None:
        self.writer.save_json(
            "text_blocks/blocks.json",
            [b.model_dump(mode="json") for b in self.all_blocks],
            "text",
        )
        self.writer.save_json(
            "geometry/pages.json",
            [p.model_dump(mode="json") for p in self.geometry],
            "geometry",
        )
        self.writer.save_json(
            "geometry/topology_candidates.json",
            [c.model_dump(mode="json") for c in self.boundaries],
            "geometry",
        )
        self.writer.save_json("geometry/feature_evidence.json", self.feature_evidence, "geometry")
        self.writer.save_json("geometry/tables.json", self.tables, "geometry")

    def _document(self) -> Document:
        matched = sorted({feature for group in self.per_page for feature in group})
        relevance: Literal["candidate", "quarantined"] = "quarantined"
        reason = "Insufficient text evidence; image-only and uncertain sources retained for review"
        if len(matched) >= 2:
            relevance = "candidate"
            reason = "At least two security feature categories in native text or local OCR"
        metadata = self.doc.metadata or {}
        return Document(
            download=self.download,
            extractor_version=__version__,
            extraction_fingerprint=fingerprint(self.options),
            pymupdf_version=pymupdf.VersionBind,
            title=metadata.get("title") or Path(self.download.path).name,
            page_count=self.doc.page_count,
            matched_features=matched,
            relevance=relevance,
            relevance_reason=reason,
            assets=self.writer.assets,
            warnings=self.warnings,
        )


def extract(download: Download, root_string: str, options: Options) -> Document:
    root = Path(root_string)
    state = download.source.discovery_jurisdiction
    target_relative = Path(state) / "derived" / download.sha256 / fingerprint(options)
    target = root / target_relative
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".extract-", dir=target.parent))
    writer = AssetWriter(staging, target_relative, options.max_asset_bytes)
    try:
        with pymupdf.open(within(root, download.path)) as doc:
            validate_pdf(doc, options)
            result = DocumentExtractor(doc, download, options, writer).run()
        atomic_json(staging / "document.json", result.model_dump(mode="json"))
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
        return result
    finally:
        if staging.exists():
            shutil.rmtree(staging)
