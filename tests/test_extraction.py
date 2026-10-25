from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest

from state_id_harvester.extract import ExtractionLimit, extract, features
from state_id_harvester.library import validate_document
from state_id_harvester.models import Download, Options, Source, TextBlock
from state_id_harvester.storage import digest, within
from state_id_harvester.topology import normalize_regions


def fixture_pdf(root: Path, *, rotated: bool = False, scanned: bool = False) -> Download:
    """Synthetic fixtures exercise mechanics; they are not credential qualification evidence."""
    path = root / "CA/raw_pdfs/fixture.pdf"
    path.parent.mkdir(parents=True)
    with pymupdf.open() as doc:
        doc.new_page()
        page = doc.new_page()
        card = pymupdf.Rect(70, 160, 412.4, 375.92)
        page.draw_rect(card, color=(0, 0, 0), fill=(0.94, 0.96, 0.98))
        if not scanned:
            page.insert_text((80, 185), "SPECIMEN - microprinting and ultraviolet")
        raster = np.full((190, 300, 4), 170, dtype=np.uint8)
        raster[:, :, 3] = 220
        _, png = cv2.imencode(".png", raster)
        xref = page.insert_image(card, stream=png.tobytes())
        page.insert_image(pymupdf.Rect(70, 450, 412.4, 665.92), xref=xref)
        if rotated:
            page.set_rotation(90)
        doc.save(path)
    return Download(
        source=Source(
            discovery_jurisdiction="CA",
            url="https://dmv.ca.gov/fixture.pdf",
            discovered_via="synthetic_test",
        ),
        final_url="https://dmv.ca.gov/fixture.pdf",
        retrieved_at="2026-10-25T00:00:00+00:00",
        sha256=digest(path),
        size_bytes=path.stat().st_size,
        path=path.relative_to(root).as_posix(),
        content_type="application/pdf",
        publisher_host="dmv.ca.gov",
        publisher_jurisdiction="CA",
    )


def test_feature_categories_do_not_double_count_synonyms() -> None:
    assert features("365 nm 365nm ultraviolet UV") == ["ultraviolet"]
    assert features("look-through look through") == ["look_through"]
    assert features("streamlined client services voided application") == []


def test_native_stream_masks_placements_and_rotated_geometry(tmp_path: Path) -> None:
    download = fixture_pdf(tmp_path, rotated=True)
    document = extract(download, str(tmp_path), Options(dpi=100, max_render_pages=2))
    assert document.relevance == "candidate"
    assert not validate_document(document, tmp_path)
    geometry_asset = next(a for a in document.assets if a.path.endswith("geometry/pages.json"))
    pages = json.loads((tmp_path / geometry_asset.path).read_text())
    assert pages[1]["rotation"] == 90
    image = pages[1]["images"][0]
    assert len(image["placements"]) == 2
    assert len([a for a in document.assets if a.kind == "extracted_image"]) == 1
    assert image["smask_stream_path"]
    with pymupdf.open(tmp_path / download.path) as doc:
        assert (tmp_path / image["raw_stream_path"]).read_bytes() == doc.xref_stream_raw(
            image["xref"]
        )
        assert (tmp_path / image["smask_stream_path"]).read_bytes() == doc.xref_stream_raw(
            image["smask_xref"]
        )
    topology_asset = next(a for a in document.assets if a.path.endswith("topology_candidates.json"))
    proposals = json.loads((tmp_path / topology_asset.path).read_text())
    assert len(proposals) >= 2
    assert all(c["metric_accuracy_mm"] is None for c in proposals)
    assert all(c["review_status"] == "unreviewed" for c in proposals)
    assert all(c["physical_calibration"] == "none" for c in proposals)
    # Tampering must invalidate a resume receipt.
    first = document.assets[0]
    (tmp_path / first.path).write_bytes(b"tampered")
    assert validate_document(document, tmp_path)


def test_image_only_pdf_is_quarantined_and_preserved(tmp_path: Path) -> None:
    download = fixture_pdf(tmp_path, scanned=True)
    document = extract(download, str(tmp_path), Options(dpi=72, max_render_pages=2))
    assert document.relevance == "quarantined"
    assert (tmp_path / download.path).exists()
    assert any(a.kind == "extracted_image" for a in document.assets)
    assert any("OCR" in w for w in document.warnings)


def test_page_budget_keeps_source_and_cleans_partial_derivatives(tmp_path: Path) -> None:
    download = fixture_pdf(tmp_path)
    with pytest.raises(ExtractionLimit, match="pages"):
        extract(download, str(tmp_path), Options(max_pages=1))
    assert (tmp_path / download.path).exists()
    assert not list(tmp_path.rglob(".extract-*"))


def test_asset_byte_budget_keeps_source(tmp_path: Path) -> None:
    download = fixture_pdf(tmp_path)
    with pytest.raises(ExtractionLimit, match="byte budget"):
        extract(download, str(tmp_path), Options(max_asset_bytes=1))
    assert (tmp_path / download.path).exists()


def test_pixel_budget_records_skipped_plate(tmp_path: Path) -> None:
    download = fixture_pdf(tmp_path)
    document = extract(download, str(tmp_path), Options(max_pixels=1, detect_boundaries=False))
    assert not any(a.kind == "page_render" for a in document.assets)
    geometry = next(a for a in document.assets if a.path.endswith("geometry/pages.json"))
    assert (
        json.loads((tmp_path / geometry.path).read_text())[1]["render_skip_reason"]
        == "Page pixel budget"
    )


def test_perspective_normalization_excludes_external_callouts() -> None:
    corners = np.array([[10, 20], [210, 20], [210, 120], [10, 120]], dtype=np.float32)
    blocks = [
        TextBlock(page_number=1, bbox=(30.0, 40.0, 110.0, 70.0), text="DOB"),
        TextBlock(page_number=1, bbox=(0.0, 0.0, 5.0, 5.0), text="External callout"),
    ]
    regions = normalize_regions(corners, blocks, 85.60, 53.98)
    assert len(regions) == 1
    assert regions[0].bbox_uv == pytest.approx((0.1, 0.2, 0.5, 0.5))
    assert regions[0].bbox_mm_nominal == pytest.approx((8.56, 10.796, 42.8, 26.99))


def test_source_paths_cannot_escape_library(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        within(tmp_path, "../secret")


def test_source_hash_is_of_retained_bytes(tmp_path: Path) -> None:
    download = fixture_pdf(tmp_path)
    assert download.sha256 == hashlib.sha256((tmp_path / download.path).read_bytes()).hexdigest()
