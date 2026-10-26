"""Native extraction mechanics; synthetic PDFs are not credential qualification evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest

from state_id_harvester.extraction_assets import AssetWriter, ExtractionLimit
from state_id_harvester.extraction_pages import NativeImages
from state_id_harvester.models import Options
from state_id_harvester.pdf_components import component_groups
from state_id_harvester.pdf_objects import InventoryLimits, inventory_page
from state_id_harvester.topology import detect

SHA = "a" * 64


def raster(width: int, height: int, *, alpha: bool = False) -> bytes:
    pixels = np.zeros((height, width, 4 if alpha else 3), dtype=np.uint8)
    pixels[:, :, :3] = (30, 180, 240)
    pixels[::3, ::4, :3] = (250, 20, 180)
    if alpha:
        pixels[:, :, 3] = 210
    ok, encoded = cv2.imencode(".png", pixels)
    assert ok
    return encoded.tobytes()


def test_small_card_and_logo_both_preserved_classification_separate(tmp_path: Path) -> None:
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((20, 30), "Driver license reference SPECIMEN")
        card = page.insert_image(pymupdf.Rect(40, 80, 269, 226), stream=raster(229, 146))
        logo = page.insert_image(pymupdf.Rect(20, 45, 35, 55), stream=raster(12, 8))
        writer = AssetWriter(tmp_path, Path("private"), 2_000_000)
        images = NativeImages(doc, Options(), writer, []).read(page, 1)
        assert {image.xref for image in images} == {card, logo}
        assert {(image.width, image.height) for image in images} == {(229, 146), (12, 8)}
        for image in images:
            raw = next(asset for asset in writer.assets if asset.path == image.raw_stream_path)
            assert raw.sha256 == hashlib.sha256(doc.xref_stream_raw(image.xref)).hexdigest()
        inventory = inventory_page(page, source_sha256=SHA, page_number=1)
        groups = component_groups(inventory, max_image_pixels=40_000_000)
        by_xref = {g.image_object_id: g for g in groups}
        assert by_xref[f"xref:{card}"].status == "reference_candidate"
        assert by_xref[f"xref:{logo}"].status == "abstained"
        proposals = detect(page, [], 1, inventory=inventory, groups=groups)
        assert len(proposals) == 1
        candidate, encoded = proposals[0]
        assert encoded == doc.extract_image(card)["image"]
        assert candidate.native_provenance is not None
        assert candidate.native_provenance["output_dimensions_px"] == [229, 146]
        assert candidate.native_provenance["effective_ppi_at_pdf_placement"] == pytest.approx(
            [72, 72]
        )
        assert candidate.native_provenance["resampling"] == "none"
        assert candidate.text_regions == []


def test_native_overlay_is_separate_without_pixel_erasure() -> None:
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((20, 30), "Driver license reference")
        xref = page.insert_image(pymupdf.Rect(40, 80, 269, 226), stream=raster(229, 146))
        original = doc.extract_image(xref)["image"]
        page.draw_circle((100, 100), 8, color=(1, 0, 0), fill=(1, 0, 0))
        page.insert_text((98, 103), "1", color=(1, 1, 1))
        inv = inventory_page(page, source_sha256=SHA, page_number=1)
        image = next(image for image in inv.images if image.xref == xref)
        image_paint = image.paint_ids[0]
        assert inv.paints[int(image_paint.rsplit(":", 1)[1])].kind == "fill-image"
        groups = component_groups(inv, max_image_pixels=1_000_000)
        group = next(g for g in groups if g.image_object_id == f"xref:{xref}")
        assert group.later_overlapping_paint_ids
        assert any(p.paint_id in group.later_overlapping_paint_ids for p in inv.paths)
        assert any(t.paint_id in group.later_overlapping_paint_ids for t in inv.text_runs)
        candidate, encoded = detect(page, [], 1, inventory=inv, groups=groups)[0]
        assert encoded == original
        assert candidate.native_provenance is not None
        assert candidate.native_provenance["annotation_content"] == "not_determined"
        assert candidate.native_provenance["mask_composition"] == "not_applied"
        assert any("not a complete" in limit for limit in inv.limitations)


def test_same_bounds_repeated_form_masks_clips_are_explicitly_ambiguous() -> None:
    with pymupdf.open() as source, pymupdf.open() as doc:
        original = source.new_page(width=300, height=200)
        original.insert_image(original.rect, stream=raster(229, 146, alpha=True))
        original.draw_rect(pymupdf.Rect(0, 0, 300, 200), color=(1, 0, 0))
        page = doc.new_page()
        target = pymupdf.Rect(20, 50, 320, 250)
        page.show_pdf_page(target, source, 0)
        page.show_pdf_page(target, source, 0)
        page.set_rotation(90)
        inv = inventory_page(page, source_sha256=SHA, page_number=1)
        assert page.rotation == 90
        assert inv.source_rotation == 90
        assert len(inv.images) == 2
        assert len({image.object_id for image in inv.images}) == 1
        assert all(image.paint_association == "ambiguous_bbox_match" for image in inv.images)
        assert all(len(image.paint_ids) == 2 for image in inv.images)
        assert all(image.clip_association == "unknown" for image in inv.images)
        assert inv.forms
        assert all("multiplicity_unknown" in form.occurrence_status for form in inv.forms)
        assert any(path.kind == "clip" for path in inv.paths)
        assert any(obj.kind == "mask" for obj in inv.objects)
        assert all(
            obj.raw_stream_sha256 for obj in inv.objects if obj.kind in {"image", "form", "mask"}
        )
        encoded = inv.model_dump(mode="json")
        assert json.loads(json.dumps(encoded))["source_sha256"] == SHA
        assert not detect(page, [], 1, inventory=inv)


def test_optional_content_object_and_layer_observation_not_visibility_verdict() -> None:
    with pymupdf.open() as doc:
        page = doc.new_page()
        layer = doc.add_ocg("Review overlay", on=True)
        image = page.insert_image(pymupdf.Rect(40, 80, 269, 226), stream=raster(229, 146), oc=layer)
        page.insert_text((20, 30), "Layer-labelled native text", oc=layer)
        inv = inventory_page(page, source_sha256=SHA, page_number=1)
        assert any(obj.xref == layer and obj.kind == "ocg" for obj in inv.objects)
        obj = next(obj for obj in inv.objects if obj.xref == image)
        assert obj.mask_keys["OC"] == ("xref", f"{layer} 0 R")
        assert any(paint.layer == "Review overlay" for paint in inv.paints)
        assert any("visibility semantics" in limit for limit in inv.limitations)


def test_administrative_ui_and_unlabelled_rectangles_abstain_keep_inventory() -> None:
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((20, 30), "Business account: Pay for a License. Click Pay Fee button.")
        page.insert_text((20, 50), "Driver license reference mentioned in help text")
        page.insert_image(pymupdf.Rect(40, 80, 269, 226), stream=raster(229, 146))
        page.draw_rect(pymupdf.Rect(40, 300, 269, 446), color=(0, 0, 0))
        inv = inventory_page(page, source_sha256=SHA, page_number=1)
        groups = component_groups(inv, max_image_pixels=1_000_000)
        assert all(g.status == "abstained" for g in groups)
        assert any("administrative" in reason for g in groups for reason in g.reasons)
        assert inv.images and inv.paths and inv.text_runs and inv.content_stream_ids
        assert not detect(page, [], 1, inventory=inv, groups=groups)


def test_inventory_record_budget_restores_rotation_and_abstains() -> None:
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((20, 30), "A long native text span")
        page.insert_text((20, 50), "Another native text span")
        page.set_rotation(90)
        limits = InventoryLimits(max_paint_operations=1)
        with pytest.raises(ExtractionLimit, match="paint budget"):
            inventory_page(page, source_sha256=SHA, page_number=1, limits=limits)
        assert page.rotation == 90


def test_font_program_and_source_content_form_streams_are_retained(tmp_path: Path) -> None:
    from state_id_harvester.extraction_objects import NativeObjectStreams

    with pymupdf.open() as doc:
        page = doc.new_page()
        font = pymupdf.Font("helv")
        xref = page.insert_font(fontname="embedded", fontbuffer=font.buffer)
        page.insert_text((20, 40), "Embedded source font", fontname="embedded")
        inv = inventory_page(page, source_sha256=SHA, page_number=1)
        resource = next(obj for obj in inv.objects if obj.xref == xref)
        assert resource.kind == "font"
        assert resource.extracted_font_program_sha256
        # MuPDF embeds this fixture as Type0: descriptor references remain in
        # the descendant-font array rather than a direct FontDescriptor key.
        assert resource.resource_keys["DescendantFonts"][0] == "array"
        assert "0 R" in resource.resource_keys["DescendantFonts"][1]
        writer = AssetWriter(tmp_path, Path("private"), 2_000_000)
        paths = NativeObjectStreams(doc, writer).preserve(inv)
        font_path = next(
            record["font_program_path"] for record in paths if record["object_id"] == f"xref:{xref}"
        )
        data = (tmp_path / font_path.removeprefix("private/")).read_bytes()
        assert hashlib.sha256(data).hexdigest() == resource.extracted_font_program_sha256
        for content in inv.content_stream_ids:
            record = next(record for record in paths if record["object_id"] == content)
            raw = (tmp_path / record["raw_stream_path"].removeprefix("private/")).read_bytes()
            assert raw == doc.xref_stream_raw(int(content.split(":")[1]))


def test_image_budget_skips_digest_lookup_keeps_resource_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pymupdf.open() as doc:
        page = doc.new_page()
        xref = page.insert_image(pymupdf.Rect(40, 80, 269, 226), stream=raster(229, 146))

        def forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError("digest lookup must not run beyond pixel budget")

        monkeypatch.setattr(pymupdf.Page, "get_image_info", forbidden)
        limits = InventoryLimits(max_image_pixels=1)
        inv = inventory_page(page, source_sha256=SHA, page_number=1, limits=limits)
        assert not inv.images
        assert any(obj.xref == xref and obj.raw_stream_sha256 for obj in inv.objects)
        assert any("pixel budget exceeded" in limitation for limitation in inv.limitations)


def test_cropped_rotated_page_geometry_is_unrotated() -> None:
    with pymupdf.open() as doc:
        page = doc.new_page(width=600, height=800)
        page.set_cropbox(pymupdf.Rect(30, 50, 500, 700))
        page.insert_text((20, 30), "Native crop-relative coordinates")
        page.set_rotation(90)
        inv = inventory_page(page, source_sha256=SHA, page_number=1)
        assert inv.page_bbox == (0, 0, 470, 650)
        assert inv.source_rotation == page.rotation == 90
        assert inv.text_runs[0].bbox[0] == pytest.approx(20)
