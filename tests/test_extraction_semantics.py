"""Normal-harvest integration mechanics, not credential qualification evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pymupdf
import pytest

from state_id_harvester.document_semantics import PageSemantics, analyze_page
from state_id_harvester.extract import extract, fingerprint
from state_id_harvester.library import validate_document
from state_id_harvester.models import Document, Download, Options, Source, TextBlock
from state_id_harvester.storage import digest


def source_fixture(root: Path) -> Download:
    path = root / "WA/raw_pdfs/native-context.pdf"
    path.parent.mkdir(parents=True)
    with pymupdf.open() as document:
        page = document.new_page(width=700, height=900)
        page.insert_text((90, 150), "Old driver license:", fontname="hebo", fontsize=14)
        page.insert_text((380, 150), "Revised driver license:", fontname="hebo", fontsize=14)
        page.insert_text((90, 185), "1. Previous serial convention.", fontsize=10)
        page.insert_text((380, 185), "1. Revised serial convention.", fontsize=10)
        pixels = np.full((90, 140, 3), 180, dtype=np.uint8)
        ok, encoded = cv2.imencode(".png", pixels)
        assert ok
        xref = page.insert_image(pymupdf.Rect(90, 220, 270, 335), stream=encoded.tobytes())
        page.insert_image(pymupdf.Rect(380, 220, 560, 335), xref=xref)
        page.set_cropbox(pymupdf.Rect(50, 70, 650, 850))
        page.set_rotation(90)
        second = document.new_page()
        second.insert_text((40, 80), "Source appendix:", fontname="hebo", fontsize=14)
        second.insert_text((40, 110), "Retained native narrative.", fontsize=11)
        document.save(path)
    return Download(
        source=Source(
            discovery_jurisdiction="WA",
            url="https://lcb.wa.gov/mechanics.pdf",
            discovered_via="synthetic_integration_test",
        ),
        final_url="https://lcb.wa.gov/mechanics.pdf",
        retrieved_at="2026-10-25T00:00:00+00:00",
        sha256=digest(path),
        size_bytes=path.stat().st_size,
        path=path.relative_to(root).as_posix(),
        content_type="application/pdf",
        publisher_host="lcb.wa.gov",
        publisher_jurisdiction="WA",
    )


def record(root: Path, document: Document, name: str) -> Any:
    asset = next(asset for asset in document.assets if asset.path.endswith(f"geometry/{name}.json"))
    return json.loads((root / asset.path).read_text())


def synthetic_ocr(page: pymupdf.Page, number: int) -> tuple[list[TextBlock], bytes]:
    assert page.rotation == 0
    native = page.search_for("1. Previous serial convention.")[0]
    return [
        TextBlock(
            page_number=number,
            bbox=tuple(native),
            text="Previous serial convention.",
            method="local_ocr",
            ocr_confidence=99,
        ),
        TextBlock(
            page_number=number,
            bbox=(60.0, 170.0, 110.0, 185.0),
            text="oa ERM! yy Rew",
            method="local_ocr",
            ocr_confidence=21,
        ),
    ], b"synthetic mechanics-only OCR TSV"


def test_normal_harvest_joins_native_context_and_retains_ocr_without_field_zones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    download = source_fixture(tmp_path)
    monkeypatch.setattr("state_id_harvester.extract.ocr_page", synthetic_ocr)
    result = extract(download, str(tmp_path), Options(dpi=72, max_render_pages=1, ocr=True))
    assert not validate_document(result, tmp_path)
    assert digest(tmp_path / download.path) == download.sha256
    pages = record(tmp_path, result, "source_semantics")
    assert len(pages) == 2
    first = pages[0]
    assert first["source_sha256"] == download.sha256
    assert first["page_bbox"] == [0.0, 0.0, 600.0, 780.0]
    assert first["native_inventory_status"] == "source_checked_and_joined"
    old, revised = sorted(first["image_contexts"], key=lambda image: image["placement_bbox"][0])
    assert old["xref"] == revised["xref"]
    assert old["native_placement_id"] != revised["native_placement_id"]
    assert old["native_object_refs"]
    assert old["native_paint_ids"]
    assert old["section_id"] != revised["section_id"]
    assert not set(old["observation_ids"]) & set(revised["observation_ids"])
    inventory_image = record(tmp_path, result, "native_objects")[0]["images"][0]
    assert old["placement_bbox"] == pytest.approx(inventory_image["placement_bbox"])
    assert first["sections"][0]["heading_bbox"][0] == 40
    assert any(line["disposition"] == "duplicate" for line in first["source_lines"])
    garbage = next(line for line in first["source_lines"] if "oa ERM!" in line["verbatim_text"])
    assert garbage["disposition"] == "image_transcription"
    assert all("oa ERM!" not in item["verbatim_text"] for item in first["observations"])
    assert "bbox_uv" not in json.dumps(pages)
    proposals = record(tmp_path, result, "topology_candidates")
    assert len(proposals) == 2
    assert all(candidate["text_regions"] == [] for candidate in proposals)
    assert record(tmp_path, result, "pages")[0]["rotation"] == 90
    statuses = record(tmp_path, result, "source_semantics_status")
    assert all(status["status"] == "observed_unreviewed" for status in statuses)
    assert all(status["review_request_status"] == "available_not_executed" for status in statuses)
    requests = record(tmp_path, result, "semantic_review_requests")
    assert len(requests) == 2
    assert requests[0]["page"]["source_sha256"] == download.sha256


def test_semantics_runs_on_every_page_without_render_or_ocr_slots(tmp_path: Path) -> None:
    download = source_fixture(tmp_path)
    result = extract(download, str(tmp_path), Options(max_render_pages=0, ocr=True))
    assert len(record(tmp_path, result, "source_semantics")) == 2
    assert not any(asset.kind == "page_render" for asset in result.assets)
    assert not any(asset.path.endswith("_ocr.tsv") for asset in result.assets)


def test_unsupported_semantics_records_failure_and_preserves_other_pages_and_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    download = source_fixture(tmp_path)

    def unsupported(page: Any, **kwargs: Any) -> PageSemantics:
        if kwargs["page_number"] == 1:
            raise ValueError("Unsupported native source semantics")
        return analyze_page(page, **kwargs)

    monkeypatch.setattr("state_id_harvester.extract.analyze_page", unsupported)
    result = extract(download, str(tmp_path), Options(max_render_pages=0))
    assert not validate_document(result, tmp_path)
    assert [page["page_number"] for page in record(tmp_path, result, "source_semantics")] == [2]
    statuses = record(tmp_path, result, "source_semantics_status")
    assert statuses[0]["status"] == "unsupported"
    assert statuses[0]["error"]["type"] == "ValueError"
    assert "Unsupported native" in statuses[0]["error"]["detail"]
    assert statuses[1]["status"] == "observed_unreviewed"
    assert any("p1: source semantics failed: ValueError" in warning for warning in result.warnings)
    assert len(record(tmp_path, result, "native_objects")) == 2
    assert record(tmp_path, result, "pages")[0]["rotation"] == 90
    assert digest(tmp_path / download.path) == download.sha256


def test_review_request_budget_failure_keeps_source_observations_with_explicit_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    download = source_fixture(tmp_path)

    def too_large(page: PageSemantics) -> None:
        raise ValueError("Page exceeds bounded semantic review byte budget")

    monkeypatch.setattr("state_id_harvester.extract.review_request", too_large)
    result = extract(download, str(tmp_path), Options(max_render_pages=0))
    assert len(record(tmp_path, result, "source_semantics")) == 2
    statuses = record(tmp_path, result, "source_semantics_status")
    assert all(status["status"] == "observed_unreviewed" for status in statuses)
    assert all(status["review_request_status"] == "unavailable" for status in statuses)
    assert all("byte budget" in status["review_request_error"]["detail"] for status in statuses)
    assert record(tmp_path, result, "semantic_review_requests") == []
    assert any("semantic review request failed" in warning for warning in result.warnings)


@pytest.mark.parametrize("module", ["document_semantics.py", "semantic_review.py"])
def test_semantic_implementation_changes_invalidate_normal_harvest_cache(
    module: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.read_bytes
    baseline = fingerprint(Options())

    def changed(path: Path) -> bytes:
        content = original(path)
        return content + b"\n# semantic implementation changed" if path.name == module else content

    monkeypatch.setattr(Path, "read_bytes", changed)
    assert fingerprint(Options()) != baseline
