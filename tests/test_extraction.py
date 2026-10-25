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


def test_failed_refresh_keeps_previous_derivatives_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from state_id_harvester.extraction_pages import PageRenderer

    download = fixture_pdf(tmp_path)
    options = Options(dpi=72, detect_boundaries=False)
    previous = extract(download, str(tmp_path), options)
    receipt = next(tmp_path.rglob("derived/*/*/document.json"))
    previous_bytes = receipt.read_bytes()
    previous_hashes = {asset.path: digest(tmp_path / asset.path) for asset in previous.assets}

    def fail(*args: object, **kwargs: object) -> str:
        raise RuntimeError("Injected renderer failure")

    monkeypatch.setattr(PageRenderer, "_plate", fail)
    with pytest.raises(RuntimeError, match="Injected renderer failure"):
        extract(download, str(tmp_path), options)
    assert receipt.read_bytes() == previous_bytes
    assert {path: digest(tmp_path / path) for path in previous_hashes} == previous_hashes
    assert digest(tmp_path / download.path) == download.sha256
    assert not list(tmp_path.rglob(".extract-*"))


def test_each_new_extraction_helper_invalidates_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from state_id_harvester.extract import fingerprint

    original_read = Path.read_bytes
    baseline = fingerprint(Options())
    for module in ("extraction_assets.py", "extraction_pages.py", "extraction_text.py"):

        def changed(path: Path, changed_module: str = module) -> bytes:
            data = original_read(path)
            return data + b"\n# changed implementation" if path.name == changed_module else data

        with monkeypatch.context() as patch:
            patch.setattr(Path, "read_bytes", changed)
            assert fingerprint(Options()) != baseline
    assert fingerprint(Options(workers=8, refresh=True)) == baseline


def test_cross_page_image_reuse_keeps_each_placement_but_one_stream(tmp_path: Path) -> None:
    download = fixture_pdf(tmp_path)
    path = tmp_path / download.path
    with pymupdf.open(path) as doc:
        xref = doc[1].get_images(full=True)[0][0]
        doc.new_page().insert_image(pymupdf.Rect(50, 50, 350, 240), xref=xref)
        doc.saveIncr()
    download = download.model_copy(
        update={"sha256": digest(path), "size_bytes": path.stat().st_size}
    )
    result = extract(download, str(tmp_path), Options(max_render_pages=0))
    geometry = next(a for a in result.assets if a.path.endswith("geometry/pages.json"))
    pages = json.loads((tmp_path / geometry.path).read_text())
    first, second = pages[1]["images"][0], pages[2]["images"][0]
    assert len(first["placements"]) == 2
    assert len(second["placements"]) == 1
    assert first["raw_stream_path"] == second["raw_stream_path"]
    assert len([a for a in result.assets if a.kind == "extracted_image"]) == 1
    assert not any(a.kind in {"page_render", "card_candidate"} for a in result.assets)
    assert not validate_document(result, tmp_path)


def test_oversized_native_image_is_not_decoded_or_lost_from_source(tmp_path: Path) -> None:
    download = fixture_pdf(tmp_path)
    result = extract(
        download,
        str(tmp_path),
        Options(max_image_pixels=1, max_render_pages=0, detect_boundaries=False),
    )
    assert not any(a.kind in {"raw_stream", "extracted_image"} for a in result.assets)
    assert any("image pixel limit exceeded" in warning for warning in result.warnings)
    assert digest(tmp_path / download.path) == download.sha256


def test_ocr_runs_unrotated_and_retains_source_rotation_and_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download = fixture_pdf(tmp_path, rotated=True, scanned=True)
    observed_rotations: list[int] = []

    def local_ocr(page: pymupdf.Page, number: int) -> tuple[list[TextBlock], bytes]:
        observed_rotations.append(page.rotation)
        return [
            TextBlock(
                page_number=number,
                bbox=(80.0, 170.0, 160.0, 190.0),
                text="Ultraviolet microprinting",
                method="local_ocr",
                ocr_confidence=95.0,
            )
        ], b"synthetic mechanics-only OCR TSV"

    monkeypatch.setattr("state_id_harvester.extract.ocr_page", local_ocr)
    result = extract(
        download,
        str(tmp_path),
        Options(
            dpi=72,
            max_render_pages=1,
            ocr=True,
            detect_boundaries=False,
        ),
    )
    assert observed_rotations == [0]
    assert result.relevance == "candidate"
    geometry = next(a for a in result.assets if a.path.endswith("geometry/pages.json"))
    pages = json.loads((tmp_path / geometry.path).read_text())
    assert pages[1]["rotation"] == 90
    blocks_asset = next(a for a in result.assets if a.path.endswith("text_blocks/blocks.json"))
    blocks = json.loads((tmp_path / blocks_asset.path).read_text())
    assert blocks[0]["bbox"] == [80.0, 170.0, 160.0, 190.0]
    assert blocks[0]["method"] == "local_ocr"
    assert any(a.path.endswith("p2_ocr.tsv") for a in result.assets)


def test_boundary_proposals_reject_off_page_distorted_and_degenerate_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from state_id_harvester.topology import rank_proposals

    good = np.array([[40, 50], [211.2, 50], [211.2, 157.96], [40, 157.96]], dtype=np.float32)
    invalid = [good - 200, np.zeros((4, 2), dtype=np.float32), good * [0.3, 1]]
    monkeypatch.setattr(
        "state_id_harvester.topology.proposals",
        lambda page: [
            ("image_placement", good, 0.65),
            *(("contour", corners.astype(np.float32), 0.45) for corners in invalid),
        ],
    )
    with pymupdf.open() as doc:
        page = doc.new_page(width=400, height=400)
        ranked = rank_proposals(page)
    assert len(ranked) == 1
    assert np.array_equal(ranked[0][2], good)


def test_polygon_deduplication_keeps_separate_card_positions() -> None:
    from state_id_harvester.topology import overlaps_existing

    first = np.array([[0, 0], [200, 0], [200, 126], [0, 126]], dtype=np.float32)
    assert overlaps_existing(first + np.array([1, 1], dtype=np.float32), [first])
    assert not overlaps_existing(first + np.array([300, 0], dtype=np.float32), [first])


def test_pixel_budget_and_asset_budget_cleanup_leave_no_partial_stage(tmp_path: Path) -> None:
    download = fixture_pdf(tmp_path)
    with pytest.raises(ExtractionLimit, match="byte budget"):
        extract(download, str(tmp_path), Options(dpi=72, max_asset_bytes=100))
    assert not list(tmp_path.rglob(".extract-*"))
    assert not list(tmp_path.rglob("derived/*/*/document.json"))
    assert digest(tmp_path / download.path) == download.sha256
