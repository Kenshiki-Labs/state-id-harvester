"""Bounded observations from MuPDF's native PDF interpreter.

This is not a second PDF interpreter. Paint sequence numbers come from MuPDF;
resource dictionaries and source stream hashes remain available for inspection.
Form definitions are not represented as proven Form invocation occurrences, and
image clipping associations remain unknown where the public API cannot prove them.
All geometry uses unrotated MuPDF page points (72 points per inch).
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Literal

from pydantic import Field

from .extraction_assets import ExtractionLimit, box, matrix
from .models import SHA256_PATTERN, Record

BBox = tuple[float, float, float, float]


class InventoryLimits(Record):
    max_image_pixels: int = Field(default=40_000_000, ge=1)
    max_paint_operations: int = Field(default=30_000, ge=1)
    max_text_characters: int = Field(default=200_000, ge=1)
    max_path_items: int = Field(default=100_000, ge=1)
    max_resource_objects: int = Field(default=2_000, ge=1)
    max_dictionary_characters: int = Field(default=2_000_000, ge=1)


class NativeObject(Record):
    object_id: str
    xref: int
    kind: Literal["page", "content_stream", "form", "image", "mask", "font", "ocg"]
    dictionary: str
    dictionary_sha256: str
    raw_stream_sha256: str | None = None
    raw_stream_bytes: int | None = None
    invoker_xrefs: list[int] = Field(default_factory=list)
    resource_names: list[str] = Field(default_factory=list)
    mask_keys: dict[str, tuple[str, str]] = Field(default_factory=dict)
    resource_keys: dict[str, tuple[str, str]] = Field(default_factory=dict)
    extracted_font_program_sha256: str | None = None
    extracted_font_program_bytes: int | None = None
    extracted_font_program_format: str | None = None


class NativePaint(Record):
    paint_id: str
    seqno: int
    kind: str
    bbox: BBox
    layer: str | None


class NativeText(Record):
    text_id: str
    paint_id: str
    bbox: BBox
    text: str
    font: str
    size: float
    flags: int
    direction: tuple[float, float]
    color: list[float]
    opacity: float
    render_type: int
    layer: str | None
    glyphs: list[dict[str, Any]]


class NativePath(Record):
    path_id: str
    kind: str
    paint_id: str | None
    level: int
    layer: str | None
    properties: dict[str, Any]
    items: list[Any]


class NativeImagePlacement(Record):
    placement_id: str
    object_id: str | None
    xref: int
    width_px: int
    height_px: int
    placement_bbox: BBox
    transform: tuple[float, float, float, float, float, float]
    effective_ppi: tuple[float, float] | None
    paint_ids: list[str]
    paint_association: Literal["unique_bbox_match", "ambiguous_bbox_match", "unresolved"]
    clip_association: Literal["unknown"] = "unknown"
    image_digest_md5: str
    has_mask: bool


class FormResource(Record):
    object_id: str
    xref: int
    resource_name: str
    invoker_xref: int
    declared_bbox: BBox
    occurrence_status: Literal["definition_only_invocation_multiplicity_unknown"] = (
        "definition_only_invocation_multiplicity_unknown"
    )


class PageObjectInventory(Record):
    schema_version: Literal[1] = 1
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    page_number: int
    page_xref: int
    source_rotation: int
    page_bbox: BBox
    coordinate_system: Literal["unrotated_mupdf_points"] = "unrotated_mupdf_points"
    pdf_to_mupdf_matrix: tuple[float, float, float, float, float, float]
    resources: tuple[str, str]
    content_stream_ids: list[str]
    objects: list[NativeObject]
    forms: list[FormResource]
    paints: list[NativePaint]
    text_runs: list[NativeText]
    paths: list[NativePath]
    images: list[NativeImagePlacement]
    limitations: list[str] = Field(
        default_factory=lambda: [
            "MuPDF native observations; not a complete source operator reconstruction",
            "Image-to-paint links use bbox equality and remain ambiguous for repeated bounds",
            "Clip/group records are retained; image active-clip associations are unknown",
            "Form resources are definitions; their invocation occurrences are not reconstructed",
            "Optional-content layer names are observations, not complete visibility semantics",
            "Inline image bytes remain in retained content streams; no invented xref is assigned",
            "Native image extent is not a reviewed credential perimeter",
        ]
    )


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bounded(records: Any, limit: int, label: str) -> Any:
    if len(records) > limit:
        raise ExtractionLimit(f"Native inventory {label} budget exceeded")
    return records


def _json_value(value: Any) -> Any:
    """Preserve native points, rectangles, quads and path operators as JSON values."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ExtractionLimit("Non-finite native geometry")
        return value
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    return [_json_value(item) for item in value]


def _object(doc: Any, xref: int, kind: Any, **metadata: Any) -> NativeObject:
    dictionary = doc.xref_object(xref, compressed=False)
    raw = doc.xref_stream_raw(xref) if doc.xref_is_stream(xref) else None
    return NativeObject(
        object_id=f"xref:{xref}",
        xref=xref,
        kind=kind,
        dictionary=dictionary,
        dictionary_sha256=_hash(dictionary.encode()),
        raw_stream_sha256=_hash(raw) if raw is not None else None,
        raw_stream_bytes=len(raw) if raw is not None else None,
        resource_keys={
            key: doc.xref_get_key(xref, key)
            for key in (
                "Resources",
                "Matrix",
                "BBox",
                "ColorSpace",
                "SMask",
                "Mask",
                "OC",
                "FontDescriptor",
                "DescendantFonts",
                "Encoding",
                "ToUnicode",
                "FontFile",
                "FontFile2",
                "FontFile3",
            )
        },
        **metadata,
    )


def _resource_objects(
    page: Any, limits: InventoryLimits
) -> tuple[list[NativeObject], list[FormResource]]:
    doc = page.parent
    objects = {page.xref: _object(doc, page.xref, "page")}
    for xref in page.get_contents():
        objects[xref] = _object(doc, xref, "content_stream")
    forms = []
    for xref, name, invoker, bbox in _bounded(
        page.get_xobjects(), limits.max_resource_objects, "Form resource"
    ):
        forms.append(
            FormResource(
                object_id=f"xref:{xref}",
                xref=xref,
                resource_name=name,
                invoker_xref=invoker,
                declared_bbox=box(bbox),
            )
        )
        if xref not in objects:
            objects[xref] = _object(doc, xref, "form")
        objects[xref].invoker_xrefs.append(invoker)
        objects[xref].resource_names.append(name)
    _image_objects(page, objects, limits)
    for font in page.get_fonts(full=True):
        xref = font[0]
        if xref > 0 and xref not in objects:
            objects[xref] = _object(doc, xref, "font")
            _, extension, _, program = doc.extract_font(xref)
            if program:
                objects[xref].extracted_font_program_sha256 = _hash(program)
                objects[xref].extracted_font_program_bytes = len(program)
                objects[xref].extracted_font_program_format = extension
    for xref in doc.get_ocgs():
        if xref not in objects:
            objects[xref] = _object(doc, xref, "ocg")
    _bounded(objects, limits.max_resource_objects, "resource object")
    if sum(len(obj.dictionary) for obj in objects.values()) > limits.max_dictionary_characters:
        raise ExtractionLimit("Native inventory dictionary budget exceeded")
    return list(objects.values()), forms


def _image_objects(page: Any, objects: dict[int, NativeObject], limits: InventoryLimits) -> None:
    doc = page.parent
    for entry in _bounded(
        page.get_images(full=True), limits.max_resource_objects, "image resource"
    ):
        xref, smask = entry[:2]
        if xref not in objects:
            keys = {key: doc.xref_get_key(xref, key) for key in ("SMask", "Mask", "OC")}
            objects[xref] = _object(doc, xref, "image", mask_keys=keys)
        if smask and smask not in objects:
            objects[smask] = _object(doc, smask, "mask")
        objects[xref].resource_names.append(str(entry[7]))
        objects[xref].invoker_xrefs.append(int(entry[9]))


def _text_runs(page: Any, number: int, limits: InventoryLimits) -> list[NativeText]:
    spans = page.get_texttrace()
    _bounded(spans, limits.max_paint_operations, "text run")
    if sum(len(span["chars"]) for span in spans) > limits.max_text_characters:
        raise ExtractionLimit("Native inventory text character budget exceeded")
    runs = []
    for index, span in enumerate(spans):
        glyphs = [
            {"codepoint": c[0], "glyph_id": c[1], "origin": list(c[2]), "bbox": list(c[3])}
            for c in span["chars"]
        ]
        text = "".join(chr(c[0]) if 0 <= c[0] <= 0x10FFFF else "\ufffd" for c in span["chars"])
        runs.append(
            NativeText(
                text_id=f"text:p{number}:{index}",
                paint_id=f"paint:p{number}:{span['seqno']}",
                bbox=box(span["bbox"]),
                text=text,
                font=span["font"],
                size=float(span["size"]),
                flags=int(span["flags"]),
                direction=tuple(span["dir"]),
                color=[float(v) for v in span["color"]],
                opacity=float(span["opacity"]),
                render_type=int(span["type"]),
                layer=span.get("layer", ""),
                glyphs=glyphs,
            )
        )
    return runs


def _paths(page: Any, number: int, limits: InventoryLimits) -> list[NativePath]:
    drawings = page.get_drawings(extended=True)
    _bounded(drawings, limits.max_paint_operations, "path record")
    if sum(len(d.get("items", [])) for d in drawings) > limits.max_path_items:
        raise ExtractionLimit("Native inventory path item budget exceeded")
    return [
        NativePath(
            path_id=f"path:p{number}:{index}",
            kind=drawing["type"],
            paint_id=f"paint:p{number}:{drawing['seqno']}" if "seqno" in drawing else None,
            level=drawing.get("level", 0),
            layer=drawing.get("layer", ""),
            properties=_json_value({k: v for k, v in drawing.items() if k != "items"}),
            items=_json_value(drawing.get("items", [])),
        )
        for index, drawing in enumerate(drawings)
    ]


def _image_placements(
    page: Any, number: int, paints: list[NativePaint], limits: InventoryLimits
) -> list[NativeImagePlacement]:
    # xrefs=True computes image digests inside MuPDF. Avoid that decode path
    # altogether when an image resource exceeds the caller's pixel budget.
    # Resource definitions/source streams remain recorded; placement identity
    # is explicitly unavailable on this page rather than guessed by dimensions.
    if any(entry[2] * entry[3] > limits.max_image_pixels for entry in page.get_images(full=True)):
        return []
    infos = _bounded(
        page.get_image_info(xrefs=True), limits.max_paint_operations, "image placement"
    )
    placements = []
    for index, info in enumerate(infos):
        bbox = box(info["bbox"])
        matches = [
            p.paint_id
            for p in paints
            if p.kind == "fill-image"
            and all(abs(a - b) < 0.02 for a, b in zip(bbox, p.bbox, strict=True))
        ]
        a, b, c, d, _, _ = info["transform"]
        sx, sy = math.hypot(a, b), math.hypot(c, d)
        ppi = (72 * info["width"] / sx, 72 * info["height"] / sy) if min(sx, sy) > 0 else None
        association: Literal["unique_bbox_match", "ambiguous_bbox_match", "unresolved"] = (
            "unresolved"
        )
        if matches:
            association = "unique_bbox_match" if len(matches) == 1 else "ambiguous_bbox_match"
        placements.append(
            NativeImagePlacement(
                placement_id=f"image:p{number}:{index}",
                object_id=f"xref:{info['xref']}" if info["xref"] else None,
                xref=info["xref"],
                width_px=info["width"],
                height_px=info["height"],
                placement_bbox=bbox,
                transform=matrix(info["transform"]),
                effective_ppi=ppi,
                paint_ids=matches,
                paint_association=association,
                image_digest_md5=info["digest"].hex(),
                has_mask=bool(info.get("has-mask", False)),
            )
        )
    return placements


def inventory_page(
    page: Any, *, source_sha256: str, page_number: int, limits: InventoryLimits | None = None
) -> PageObjectInventory:
    """Observe interpreted native components, preserving source-local identities."""
    limits = limits or InventoryLimits()
    rotation = page.rotation
    try:
        page.set_rotation(0)
        bboxlog = _bounded(page.get_bboxlog(layers=True), limits.max_paint_operations, "paint")
        paints = [
            NativePaint(
                paint_id=f"paint:p{page_number}:{i}", seqno=i, kind=p[0], bbox=box(p[1]), layer=p[2]
            )
            for i, p in enumerate(bboxlog)
        ]
        objects, forms = _resource_objects(page, limits)
        result = PageObjectInventory(
            source_sha256=source_sha256,
            page_number=page_number,
            page_xref=page.xref,
            source_rotation=rotation,
            page_bbox=box(page.rect),
            pdf_to_mupdf_matrix=matrix(page.transformation_matrix),
            resources=page.parent.xref_get_key(page.xref, "Resources"),
            content_stream_ids=[f"xref:{xref}" for xref in page.get_contents()],
            objects=objects,
            forms=forms,
            paints=paints,
            text_runs=_text_runs(page, page_number, limits),
            paths=_paths(page, page_number, limits),
            images=_image_placements(page, page_number, paints, limits),
        )
        if any(
            entry[2] * entry[3] > limits.max_image_pixels for entry in page.get_images(full=True)
        ):
            result.limitations.append(
                "Image resource pixel budget exceeded; image digest/placement association skipped"
            )
        return result
    finally:
        page.set_rotation(rotation)
