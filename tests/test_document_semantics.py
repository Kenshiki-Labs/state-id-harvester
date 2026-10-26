"""Mechanical contrasts; these generated diagrams are not credential evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest

from state_id_harvester.document_semantics import PageSemantics, analyze_document, analyze_page
from state_id_harvester.models import TextBlock
from state_id_harvester.semantic_review import (
    QuotedEvidence,
    SemanticClaim,
    SemanticReviewProposal,
    review_request,
    validate_review,
)


@contextmanager
def two_versions() -> Iterator[tuple[pymupdf.Page, str]]:
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((40, 90), "Old driver license:", fontname="hebo", fontsize=14)
        page.insert_text((330, 90), "Revised driver license:", fontname="hebo", fontsize=14)
        page.insert_text((40, 120), "1. Previous serial number rule.", fontsize=10)
        page.insert_text((330, 120), "1. New serial number convention.", fontsize=10)
        image = np.full((90, 140, 3), 170, dtype=np.uint8)
        ok, raster = cv2.imencode(".png", image)
        assert ok
        xref = page.insert_image(pymupdf.Rect(40, 160, 220, 275), stream=raster.tobytes())
        page.insert_image(pymupdf.Rect(330, 160, 510, 275), xref=xref)
        data = document.tobytes()
    with pymupdf.open(stream=data, filetype="pdf") as source:
        yield source[0], hashlib.sha256(data).hexdigest()


def analyze_fixture() -> PageSemantics:
    with two_versions() as (page, checksum):
        return analyze_page(page, source_sha256=checksum, page_number=1)


def proposal_for(page: PageSemantics) -> SemanticReviewProposal:
    old = min(page.image_contexts, key=lambda image: image.placement_bbox[0])
    observation = next(o for o in page.observations if o.observation_id in old.observation_ids)
    line = next(line for line in page.source_lines if line.span_id == observation.span_ids[0])
    return SemanticReviewProposal(
        source_sha256=page.source_sha256,
        page_number=1,
        review_origin="model_backend",
        reviewer_or_backend="test backend",
        claims=[
            SemanticClaim(
                claim_id="old-statement",
                target_image_ids=[old.image_id],
                relation="source_describes",
                evidence=[QuotedEvidence(span_id=line.span_id, verbatim_quote=line.verbatim_text)],
                rationale="Source statement is in the old example's typographic section.",
                unresolved_questions=["Exact issue-date range is absent."],
            )
        ],
    )


def test_adjacent_versions_do_not_share_numbered_lists_even_with_same_image_xref() -> None:
    result = analyze_fixture()
    assert len(result.image_contexts) == 2
    old, revised = sorted(result.image_contexts, key=lambda image: image.placement_bbox[0])
    assert old.xref == revised.xref
    assert old.image_id != revised.image_id
    assert old.section_id != revised.section_id
    observations = {observation.observation_id: observation for observation in result.observations}
    assert "Previous serial" in observations[old.observation_ids[0]].verbatim_text
    assert "New serial" in observations[revised.observation_ids[0]].verbatim_text
    assert not set(old.observation_ids).intersection(revised.observation_ids)


def test_native_fonts_and_paint_sequence_are_preserved_without_field_geometry() -> None:
    result = analyze_fixture()
    native = next(line for line in result.source_lines if line.verbatim_text.startswith("Old"))
    assert native.native_runs[0].font_name
    assert native.native_runs[0].font_size == 14
    assert native.native_runs[0].paint_sequence_numbers
    assert result.image_contexts[0].paint_sequence_numbers
    assert result.image_contexts[0].source_stream_sha256
    assert result.image_contexts[0].feature_localization == "not_established"
    assert "bbox_uv" not in result.model_dump_json()


def test_ocr_duplicate_is_linked_and_image_garbage_is_never_a_narrative_or_zone() -> None:
    with two_versions() as (page, checksum):
        native = analyze_page(page, source_sha256=checksum, page_number=1)
        line = next(line for line in native.source_lines if "Previous serial" in line.verbatim_text)
        ocr = [
            TextBlock(
                page_number=1,
                bbox=line.bbox,
                text="Previous serial number rule.",
                method="local_ocr",
                ocr_confidence=99,
            ),
            TextBlock(
                page_number=1,
                bbox=(60.0, 170.0, 110.0, 180.0),
                text="oa ERM! yy Rew",
                method="local_ocr",
                ocr_confidence=22,
            ),
        ]
        result = analyze_page(page, source_sha256=checksum, page_number=1, ocr_blocks=ocr)
    duplicate = next(line for line in result.source_lines if line.disposition == "duplicate")
    assert duplicate.duplicate_of == line.span_id
    image_ocr = next(line for line in result.source_lines if "oa ERM" in line.verbatim_text)
    assert image_ocr.disposition == "image_transcription"
    assert all("oa ERM" not in observation.verbatim_text for observation in result.observations)


def test_same_text_at_another_position_is_not_deduplicated() -> None:
    with two_versions() as (page, checksum):
        block = TextBlock(
            page_number=1,
            bbox=(40.0, 650.0, 200.0, 665.0),
            text="Previous serial number rule.",
            method="local_ocr",
            ocr_confidence=99,
        )
        result = analyze_page(page, source_sha256=checksum, page_number=1, ocr_blocks=[block])
    ocr = next(line for line in result.source_lines if line.method == "local_ocr")
    assert ocr.duplicate_of is None
    assert ocr.disposition == "unresolved_ocr"


def test_wrong_page_ocr_is_rejected() -> None:
    with two_versions() as (page, checksum):
        block = TextBlock(
            page_number=2, bbox=(40.0, 80.0, 200.0, 90.0), text="Different page", method="local_ocr"
        )
        with pytest.raises(ValueError, match="source page"):
            analyze_page(page, source_sha256=checksum, page_number=1, ocr_blocks=[block])


def test_conflicting_date_statements_remain_verbatim_and_unresolved() -> None:
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((40, 80), "Driver license revision:", fontname="hebo", fontsize=14)
        page.insert_text(
            (40, 110), "Beginning September 2018 the serial number changed.", fontsize=11
        )
        page.insert_text(
            (40, 140), "Beginning October 2018 the serial number changed.", fontsize=11
        )
        result = analyze_page(page, source_sha256="a" * 64, page_number=1)
    periods = [
        quote
        for observation in result.observations
        for quote in observation.effective_period_quotes
    ]
    assert any("September" in quote for quote in periods)
    assert any("October" in quote for quote in periods)
    assert all(observation.cross_source_pairing == "pending" for observation in result.observations)
    assert "issue_date_start" not in result.model_dump_json()


def test_quote_grounding_uses_source_bbox_and_authorizes_no_runtime_rule() -> None:
    page = analyze_fixture()
    result = validate_review(page, proposal_for(page))
    assert result[0].runtime_use == "none"
    assert result[0].semantic_truth_status == "unverified_interpretation"
    assert result[0].evidence[0].source_bbox
    assert result[0].evidence[0].native_run_ids


@pytest.mark.parametrize(
    "attack", ["invented_quote", "invented_span", "wrong_source", "wrong_image", "cross_version"]
)
def test_backend_proposal_cannot_invent_or_cross_bind_evidence(attack: str) -> None:
    page = analyze_fixture()
    proposal = proposal_for(page)
    claim = proposal.claims[0]
    if attack == "invented_quote":
        claim.evidence[0].verbatim_quote = "An invented executable requirement."
    elif attack == "invented_span":
        claim.evidence[0].span_id = "unknown-native-text-object"
    elif attack == "wrong_source":
        proposal.source_sha256 = "b" * 64
    elif attack == "wrong_image":
        claim.target_image_ids = ["unknown-image-placement"]
    else:
        claim.target_image_ids = [
            max(page.image_contexts, key=lambda image: image.placement_bbox[0]).image_id
        ]
    with pytest.raises(ValueError):
        validate_review(page, proposal)


def test_narrative_comparison_is_not_permission_to_copy_field_geometry() -> None:
    data = proposal_for(analyze_fixture()).model_dump(mode="json")
    data["claims"][0]["relation"] = "source_comparison"
    data["claims"][0]["authorizes_geometry_transfer"] = True
    payload = json.dumps(data)
    with pytest.raises(ValueError):
        SemanticReviewProposal.model_validate_json(payload)


def test_backend_cannot_supply_executable_policy_or_forged_coordinates() -> None:
    data = proposal_for(analyze_fixture()).model_dump(mode="json")
    data["claims"][0]["evidence"][0]["source_bbox"] = [0, 0, 10, 10]
    data["claims"][0]["predicate"] = "eval(untrusted)"
    payload = json.dumps(data)
    with pytest.raises(ValueError):
        SemanticReviewProposal.model_validate_json(payload)


def test_native_inventory_with_a_different_source_is_rejected() -> None:
    with two_versions() as (page, checksum):
        inventory = {"source_sha256": "b" * 64, "page_number": 1}
        with pytest.raises(ValueError, match="source hash"):
            analyze_page(page, source_sha256=checksum, page_number=1, native_inventory=inventory)


def test_native_inventory_join_checks_the_image_stream_hash() -> None:
    with two_versions() as (page, checksum):
        result = analyze_page(page, source_sha256=checksum, page_number=1)
        image = result.image_contexts[0]
        inventory = {
            "source_sha256": checksum,
            "page_number": 1,
            "coordinate_system": "unrotated_mupdf_points",
            "images": [
                {
                    "xref": image.xref,
                    "placement_bbox": image.placement_bbox,
                    "object_id": f"xref:{image.xref}",
                    "placement_id": "native-image-0",
                    "paint_ids": [],
                }
            ],
            "objects": [{"object_id": f"xref:{image.xref}", "raw_stream_sha256": "b" * 64}],
            "text_runs": [],
        }
        with pytest.raises(ValueError, match="stream hash"):
            analyze_page(page, source_sha256=checksum, page_number=1, native_inventory=inventory)


def test_native_ocr_word_change_is_not_silently_deduplicated() -> None:
    with two_versions() as (page, checksum):
        page.insert_text((40, 400), "Start with WDL", fontsize=11)
        native = analyze_page(page, source_sha256=checksum, page_number=1)
        original = next(
            line for line in native.source_lines if line.verbatim_text == "Start with WDL"
        )
        block = TextBlock(
            page_number=1, bbox=original.bbox, text="Start with W0L", method="local_ocr"
        )
        result = analyze_page(page, source_sha256=checksum, page_number=1, ocr_blocks=[block])
    ocr = next(line for line in result.source_lines if line.method == "local_ocr")
    assert ocr.duplicate_of is None
    assert ocr.disposition == "unresolved_ocr"


def test_crop_offset_and_rotation_do_not_shift_native_context_coordinates() -> None:
    with pymupdf.open() as document:
        page = document.new_page(width=700, height=900)
        page.insert_text((90, 150), "Driver license example:", fontname="hebo", fontsize=14)
        page.insert_text((90, 185), "1. Source observation.", fontsize=11)
        page.set_cropbox(pymupdf.Rect(50, 70, 650, 850))
        page.set_rotation(90)
        result = analyze_page(page, source_sha256="a" * 64, page_number=1)
        assert page.rotation == 90
    assert result.page_bbox == (0.0, 0.0, 600.0, 780.0)
    assert result.sections[0].heading_bbox[0] == 40
    assert result.observations[0].source_bbox[0] == 40


def test_layout_without_a_heading_abstains_instead_of_using_page_wide_context() -> None:
    with two_versions() as (page, checksum):
        page.add_redact_annot(pymupdf.Rect(0, 0, 600, 110))
        page.apply_redactions()
        result = analyze_page(page, source_sha256=checksum, page_number=1)
    assert all(image.association_status == "unscoped" for image in result.image_contexts)
    assert all(not image.observation_ids for image in result.image_contexts)


def test_unbounded_native_text_is_rejected_before_backend_review() -> None:
    page = analyze_fixture()
    page.source_lines[0].verbatim_text = "a" * 2_000_001
    with pytest.raises(ValueError, match="byte budget"):
        review_request(page)


def load_audit_script():
    spec = importlib.util.spec_from_file_location(
        "audit_pdf_semantics", "scripts/audit_pdf_semantics.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_private_report_cli_preserves_source_and_escapes_review_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    with two_versions() as (page, _):
        source.write_bytes(page.parent.tobytes())
    original = source.read_bytes()
    with pymupdf.open(source) as document:
        result = analyze_page(
            document[0], source_sha256=hashlib.sha256(original).hexdigest(), page_number=1
        )
    proposal = proposal_for(result)
    proposal.claims[0].rationale = '<img src=x onerror="unexpected()">'
    review = tmp_path / "review.json"
    review.write_text(proposal.model_dump_json())
    output = tmp_path / "private-report"
    monkeypatch.setattr(
        sys, "argv", ["audit", str(source), str(output), "--pages", "1", "--review", str(review)]
    )
    load_audit_script().main()
    assert source.read_bytes() == original
    report = (output / "index.html").read_text()
    assert "<img src=x onerror=" not in report
    assert "&lt;img src=x onerror=" in report
    assert "Grounded review proposal" in report
    assert "inventory not joined" in report
    after = json.loads((output / "after.json").read_text())
    assert len(after[0]["image_contexts"]) == 2
    grounded = json.loads((output / "grounded-review.json").read_text())
    assert grounded[0]["semantic_truth_status"] == "unverified_interpretation"


def test_private_report_does_not_follow_existing_asset_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    with two_versions() as (page, _):
        source.write_bytes(page.parent.tobytes())
    with pymupdf.open(source) as document:
        result = analyze_page(document[0], source_sha256="a" * 64, page_number=1)
    output = tmp_path / "private-report"
    output.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"must remain unchanged")
    (output / f"{result.image_contexts[0].image_id}.png").symlink_to(outside)
    script = load_audit_script()
    with pytest.raises(ValueError, match="escapes"):
        script.export_inspection_assets(source, output, [result])
    assert outside.read_bytes() == b"must remain unchanged"


@pytest.mark.parametrize("route", ["traversal", "symlink"])
@pytest.mark.parametrize("reader", ["json", "native_inventory", "document"])
def test_audit_input_paths_cannot_escape_managed_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str, reader: str
) -> None:
    script = load_audit_script()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    temporary = tmp_path / "managed-temporary"
    temporary.mkdir()
    outside = tmp_path / "private-source.json"
    outside.write_text('{"private":true}')
    requested = checkout / "../private-source.json"
    if route == "symlink":
        requested = checkout / "linked.json"
        requested.symlink_to(outside)
    monkeypatch.chdir(checkout)
    monkeypatch.setattr("state_id_harvester.paths.tempfile.gettempdir", lambda: str(temporary))
    operations = {
        "json": lambda: script.read_json_file(requested),
        "native_inventory": lambda: script.load_inventories(
            checkout / "source.pdf", [1], requested, False
        ),
        "document": lambda: analyze_document(requested, [1]),
    }
    operation = operations[reader]
    with pytest.raises(ValueError, match="managed temporary directory"):
        operation()


@pytest.mark.parametrize("route", ["traversal", "absolute", "symlink"])
def test_report_json_writer_cannot_replace_a_file_outside_output(
    tmp_path: Path, route: str
) -> None:
    script = load_audit_script()
    output = tmp_path / "report"
    output.mkdir()
    outside = tmp_path / "keep.json"
    outside.write_text("preserve these bytes")
    name = "../keep.json" if route == "traversal" else str(outside)
    if route == "symlink":
        name = "linked.json"
        (output / name).symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        script.json_file(output, name, {"replaced": True})
    assert outside.read_text() == "preserve these bytes"


def test_report_inputs_inside_output_are_rejected_before_any_source_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = load_audit_script()
    output = tmp_path / "report"
    output.mkdir()
    source = output / "after.json"
    with two_versions() as (page, _):
        source.write_bytes(page.parent.tobytes())
    original = source.read_bytes()
    monkeypatch.setattr(sys, "argv", ["audit", str(source), str(output), "--pages", "1"])
    with pytest.raises(ValueError, match="outside the output directory"):
        script.main()
    assert source.read_bytes() == original


def test_audit_sidecar_read_is_bounded_before_json_parsing(tmp_path: Path) -> None:
    script = load_audit_script()
    script.MAX_SIDECAR_BYTES = 16
    sidecar = tmp_path / "large.json"
    sidecar.write_text('{"payload":"' + "a" * 32 + '"}')
    with pytest.raises(ValueError, match="sidecar exceeds"):
        script.read_json_file(sidecar)
