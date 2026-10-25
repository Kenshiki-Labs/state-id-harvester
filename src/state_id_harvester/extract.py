"""Loss-aware PDF extraction, executed in isolated worker processes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Literal

import pymupdf

from . import __version__
from .models import (
    Asset,
    BoundaryCandidate,
    Document,
    Download,
    ImageGeometry,
    Options,
    PageGeometry,
    Placement,
    TextBlock,
)
from .ocr import ocr_page
from .storage import atomic_json, within
from .topology import detect

FEATURE_PATTERNS: dict[str, str] = {
    "guilloche": r"\bguilloche\b",
    "tactile": r"\btactile\b|\btouchable indentations\b",
    "microprinting": r"\bmicroprint(?:ing)?\b|\bmicrotext\b",
    "ultraviolet": r"\bultraviolet\b|\buv\b|\b365\s*nm\b",
    "look_through": r"\blook[ -]?through\b|\bdlte\b",
    "ghost_portrait": r"\bghost\b",
    "polycarbonate": r"\bpolycarbonate\b",
    "laser_engraving": r"\blaser[ -]engrav(?:ed|ing)\b|\bengraved data\b",
    "optically_variable": r"\boptically variable\b|\bovd\b|\bovg\b",
    "multiple_laser_image": r"\bmli\b|\bmultiple laser image\b",
    "changeable_laser_image": r"\bcli\b|\bchangeable laser image\b",
    "lenticular": r"\blenticular\b",
    "retroreflective": r"\bretro[ -]?reflective\b",
    "tamper_void": r"\bvoid\b",
    "laser_perforation": r"\blaser perforations?\b",
    "hologram": r"\bhologram\b|\bholographic\b",
}


def features(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = re.sub(r"[\u2010-\u2015]", "-", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return sorted(
        name for name, pattern in FEATURE_PATTERNS.items() if re.search(pattern, normalized)
    )


def fingerprint(options: Options) -> str:
    data = options.model_dump(exclude={"refresh", "workers", "crawl_pages", "max_pdfs_per_state"})
    data.update(extractor=__version__, pymupdf=pymupdf.VersionBind)
    # Cache invalidation also covers unversioned local extractor/geometry edits.
    module_root = Path(__file__).parent
    data["implementation"] = hashlib.sha256(
        b"".join(
            (module_root / name).read_bytes()
            for name in ("extract.py", "topology.py", "models.py", "ocr.py")
        )
    ).hexdigest()
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


class ExtractionLimit(Exception):
    pass


def box(values: Any) -> tuple[float, float, float, float]:
    return float(values[0]), float(values[1]), float(values[2]), float(values[3])


def matrix(values: Any) -> tuple[float, float, float, float, float, float]:
    return (*box(values), float(values[4]), float(values[5]))


def extract(download: Download, root_string: str, options: Options) -> Document:
    root = Path(root_string)
    state = download.source.discovery_jurisdiction
    target_rel = Path(state) / "derived" / download.sha256 / fingerprint(options)
    target = root / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".extract-", dir=target.parent))
    assets: list[Asset] = []
    warnings: list[str] = []
    written_bytes = 0

    def save(
        name: str,
        data: bytes,
        kind: Literal[
            "extracted_image",
            "raw_stream",
            "page_render",
            "thumbnail",
            "text",
            "geometry",
            "card_candidate",
        ],
        page: int | None = None,
        xref: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> str:
        nonlocal written_bytes
        written_bytes += len(data)
        if written_bytes > options.max_asset_bytes:
            raise ExtractionLimit("Extracted asset byte budget exceeded")
        path = staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        relative = (target_rel / name).as_posix()
        assets.append(
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

    def save_json(name: str, records: Any, kind: Literal["text", "geometry"]) -> str:
        return save(
            name,
            (json.dumps(records, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(),
            kind,
        )

    try:
        with pymupdf.open(within(root, download.path)) as doc:
            if doc.needs_pass:
                raise ExtractionLimit("Encrypted PDF requires a password")
            if doc.page_count > options.max_pages:
                raise ExtractionLimit(
                    f"PDF has {doc.page_count} pages; limit is {options.max_pages}"
                )
            if not doc.is_pdf or doc.page_count == 0:
                raise ExtractionLimit("Not a nonempty PDF")
            page_texts: list[str] = [page.get_text("text") for page in doc]
            per_page = [features(text) for text in page_texts]
            matched = sorted({feature for group in per_page for feature in group})
            relevance: Literal["candidate", "quarantined"] = (
                "candidate" if len(matched) >= 2 else "quarantined"
            )
            reason = (
                "At least two independent security feature categories"
                if len(matched) >= 2
                else (
                    "Insufficient text evidence; image-only and uncertain sources "
                    "retained for review"
                )
            )
            if not any(text.strip() for text in page_texts):
                warnings.append("No extractable text; OCR/manual review required")
            all_blocks: list[TextBlock] = []
            geometry: list[PageGeometry] = []
            boundaries: list[BoundaryCandidate] = []
            feature_evidence: list[dict[str, Any]] = []
            tables: list[dict[str, Any]] = []
            extracted: dict[int, tuple[str, str | None, str | None]] = {}

            # Rank high-evidence pages first, retaining source page numbers and every skip reason.
            def page_score(n: int) -> int:
                headings = len(
                    re.findall(
                        r"security features|counterfeit|new card|card design", page_texts[n], re.I
                    )
                )
                return len(per_page[n]) * 10 + headings * 20 + min(len(doc[n].get_images()), 5)

            ranked_pages = sorted(range(doc.page_count), key=lambda n: (-page_score(n), n))
            render_slots = set(ranked_pages[: options.max_render_pages])
            for index, page in enumerate(doc):
                number = index + 1
                blocks = [
                    TextBlock(page_number=number, bbox=box(block), text=block[4])
                    for block in page.get_text("blocks")
                    if block[6] == 0 and block[4].strip()
                ]
                if options.ocr and index in render_slots and page.get_images():
                    rotation_for_ocr = page.rotation
                    try:
                        page.set_rotation(0)
                        ocr_blocks, tsv = ocr_page(page, number)
                        blocks.extend(ocr_blocks)
                        save(f"text_blocks/p{number}_ocr.tsv", tsv, "text", number)
                        per_page[index] = sorted(
                            set(per_page[index])
                            | set(features(" ".join(b.text for b in ocr_blocks)))
                        )
                    except Exception as exc:
                        warnings.append(f"p{number}: local OCR failed: {type(exc).__name__}")
                    finally:
                        page.set_rotation(rotation_for_ocr)
                all_blocks.extend(blocks)
                for block in blocks:
                    categories = features(block.text)
                    if categories:
                        feature_evidence.append(
                            {
                                "page_number": number,
                                "bbox": block.bbox,
                                "text": block.text,
                                "method": block.method,
                                "feature_categories": categories,
                                "interpretation": (
                                    "source_text_observation; not an approved runtime rule"
                                ),
                            }
                        )
                images: list[ImageGeometry] = []
                seen_xrefs: set[int] = set()
                for entry in page.get_images(full=True):
                    xref, smask, width, height = entry[:4]
                    if xref in seen_xrefs or width < 280 or height < 160:
                        continue
                    seen_xrefs.add(xref)
                    if width * height > options.max_image_pixels:
                        warnings.append(f"p{number} xref{xref}: image pixel limit exceeded")
                        continue
                    placements = [
                        Placement(
                            bbox=box(rect),
                            transform=matrix(transform),
                        )
                        for rect, transform in page.get_image_rects(xref, transform=True)
                    ]
                    if not placements:
                        continue  # Ignore unused resource entries.
                    if xref not in extracted:
                        raw = doc.xref_stream_raw(xref)
                        if raw is None:
                            warnings.append(f"p{number} xref{xref}: no raw stream")
                            continue
                        raw_path = save(
                            f"native_xrefs/xref{xref}.stream",
                            raw,
                            "raw_stream",
                            number,
                            xref,
                            width,
                            height,
                        )
                        mask_path = None
                        if smask:
                            mask = doc.xref_stream_raw(smask)
                            if mask is not None:
                                mask_path = save(
                                    f"native_xrefs/xref{xref}_smask{smask}.stream",
                                    mask,
                                    "raw_stream",
                                    number,
                                    smask,
                                )
                        image = doc.extract_image(xref)
                        extracted_path = None
                        if image:
                            ext = re.sub(r"[^a-z0-9]", "", image["ext"].lower()) or "bin"
                            extracted_path = save(
                                f"native_xrefs/xref{xref}_{width}x{height}.{ext}",
                                image["image"],
                                "extracted_image",
                                number,
                                xref,
                                width,
                                height,
                            )
                        extracted[xref] = raw_path, extracted_path, mask_path
                    raw_path, extracted_path, mask_path = extracted[xref]
                    images.append(
                        ImageGeometry(
                            xref=xref,
                            smask_xref=smask,
                            width=width,
                            height=height,
                            colorspace=str(entry[5]),
                            pdf_object=doc.xref_object(xref, compressed=False),
                            raw_stream_path=raw_path,
                            extracted_path=extracted_path,
                            smask_stream_path=mask_path,
                            placements=placements,
                        )
                    )
                render_reason = None
                rendered = False
                render_tiles: list[dict[str, object]] = []
                selected = bool(per_page[index] or images or not any(page_texts))
                pixels = math.ceil(page.rect.width * options.dpi / 72) * math.ceil(
                    page.rect.height * options.dpi / 72
                )
                if not selected:
                    render_reason = "No text feature or sufficiently large placed image"
                elif index not in render_slots:
                    render_reason = "Per-document render page budget"
                elif pixels > options.max_pixels:
                    edge = int(math.sqrt(options.max_pixels))
                    scale = options.dpi / 72
                    tile_span = max(1, edge - 2) / scale
                    cols = math.ceil(page.rect.width / tile_span)
                    rows = math.ceil(page.rect.height / tile_span)
                    if cols * rows > options.max_tiles_per_page:
                        render_reason = "Page pixel budget"
                    else:
                        for row in range(rows):
                            for col in range(cols):
                                rect = page.rect
                                clip = pymupdf.Rect(
                                    rect.x0 + col * tile_span,
                                    rect.y0 + row * tile_span,
                                    min(rect.x1, rect.x0 + (col + 1) * tile_span),
                                    min(rect.y1, rect.y0 + (row + 1) * tile_span),
                                )
                                pix = page.get_pixmap(
                                    dpi=options.dpi,
                                    clip=clip,
                                    colorspace=pymupdf.csRGB,
                                    alpha=False,
                                )
                                tile_path = save(
                                    f"pages_{options.dpi}dpi/p{number}_r{row}c{col}.png",
                                    pix.tobytes("png"),
                                    "page_render",
                                    number,
                                    width=pix.width,
                                    height=pix.height,
                                )
                                render_tiles.append(
                                    {
                                        "path": tile_path,
                                        "display_clip": box(clip),
                                        "pixel_origin": [pix.x, pix.y],
                                        "dpi": options.dpi,
                                    }
                                )
                        rendered = True
                else:
                    pix = page.get_pixmap(
                        dpi=options.dpi, colorspace=pymupdf.csRGB, alpha=False, annots=True
                    )
                    save(
                        f"pages_{options.dpi}dpi/p{number}.png",
                        pix.tobytes("png"),
                        "page_render",
                        number,
                        width=pix.width,
                        height=pix.height,
                    )
                    rendered = True
                if rendered:
                    thumb_scale = min(0.75, math.sqrt(1_000_000 / max(page.rect.get_area(), 1)))
                    thumb = page.get_pixmap(
                        matrix=pymupdf.Matrix(thumb_scale, thumb_scale),
                        colorspace=pymupdf.csRGB,
                        alpha=False,
                    )
                    save(
                        f"thumbnails/p{number}.png",
                        thumb.tobytes("png"),
                        "thumbnail",
                        number,
                        width=thumb.width,
                        height=thumb.height,
                    )
                rotation = page.rotation
                rotation_matrix = matrix(page.rotation_matrix)
                pdf_to_mupdf = matrix(page.transformation_matrix)
                # Detection is bounded to the same ranked pages; page coordinates are
                # unrotated throughout, while full-page plates retain display rotation.
                if options.detect_boundaries and index in render_slots and selected:
                    try:
                        page.set_rotation(0)
                        # Keep source cell geometry and text; do not guess normative
                        # rules from arbitrary numbers or checklist table headings.
                        if per_page[index]:
                            try:
                                finder = page.find_tables()
                                for table in finder.tables[:20]:
                                    tables.append(
                                        {
                                            "page_number": number,
                                            "bbox": box(table.bbox),
                                            "cells": [
                                                box(cell) if cell else None for cell in table.cells
                                            ],
                                            "rows": table.extract(),
                                        }
                                    )
                            except Exception as exc:
                                warnings.append(f"p{number}: table extraction {type(exc).__name__}")
                        for candidate, png in detect(page, blocks, number):
                            crop_path = save(
                                f"card_candidates/{candidate.candidate_id}.png",
                                png,
                                "card_candidate",
                                number,
                            )
                            boundaries.append(candidate.model_copy(update={"crop_path": crop_path}))
                    finally:
                        page.set_rotation(rotation)
                geometry.append(
                    PageGeometry(
                        page_number=number,
                        mediabox=box(page.mediabox),
                        cropbox=box(page.cropbox),
                        rotation=rotation,
                        rotation_matrix=rotation_matrix,
                        pdf_to_mupdf_matrix=pdf_to_mupdf,
                        matched_features=per_page[index],
                        images=images,
                        rendered=rendered,
                        render_tiles=render_tiles,
                        render_skip_reason=render_reason,
                    )
                )
            save_json(
                "text_blocks/blocks.json", [b.model_dump(mode="json") for b in all_blocks], "text"
            )
            save_json(
                "geometry/pages.json", [p.model_dump(mode="json") for p in geometry], "geometry"
            )
            save_json(
                "geometry/topology_candidates.json",
                [c.model_dump(mode="json") for c in boundaries],
                "geometry",
            )
            save_json("geometry/feature_evidence.json", feature_evidence, "geometry")
            save_json("geometry/tables.json", tables, "geometry")
            metadata = doc.metadata or {}
            matched = sorted({feature for group in per_page for feature in group})
            relevance = "candidate" if len(matched) >= 2 else "quarantined"
            if relevance == "candidate":
                reason = "At least two security feature categories in native text or local OCR"
            result = Document(
                download=download,
                extractor_version=__version__,
                extraction_fingerprint=fingerprint(options),
                pymupdf_version=pymupdf.VersionBind,
                title=metadata.get("title") or Path(download.path).name,
                page_count=doc.page_count,
                matched_features=matched,
                relevance=relevance,
                relevance_reason=reason,
                assets=assets,
                warnings=warnings,
            )
        atomic_json(staging / "document.json", result.model_dump(mode="json"))
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
        return result
    finally:
        if staging.exists():
            shutil.rmtree(staging)
