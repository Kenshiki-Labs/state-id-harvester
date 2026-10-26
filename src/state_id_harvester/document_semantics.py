"""Source-bound document layout observations, not credential validation rules.

Native lines, image placements and typography form a page graph. Geometry can
associate a paragraph with a figure; it cannot prove the paragraph is true or
that a pictured security feature exists. OCR stays a transcription observation.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import median
from typing import Any, Literal

import pymupdf
from pydantic import Field

from .models import Record, TextBlock
from .paths import managed_path

BBox = tuple[float, float, float, float]
SHA256_PATTERN = r"^[a-f0-9]{64}$"
SectionBasis = Literal["typographic_heading", "emphasized_paragraph", "page_unscoped"]
ObservationKind = Literal[
    "numbered_callout", "bullet_statement", "narrative", "applicability_statement"
]
ContextKind = Literal["credential_reference", "administrative_interface", "unknown"]


class NativeTextRun(Record):
    run_id: str
    verbatim_text: str
    bbox: BBox
    font_name: str
    font_size: float
    font_flags: int
    color: int
    origin: tuple[float, float]
    paint_sequence_numbers: list[int]
    native_text_ids: list[str] = Field(default_factory=list)


class SourceLine(Record):
    span_id: str
    page_number: int
    block_index: int
    line_index: int
    bbox: BBox
    verbatim_text: str
    method: Literal["pdf_text", "local_ocr"]
    font_size: float | None = None
    bold_fraction: float = 0
    native_runs: list[NativeTextRun] = Field(default_factory=list)
    ocr_confidence: float | None = None
    duplicate_of: str | None = None
    disposition: Literal[
        "narrative_evidence", "image_transcription", "page_furniture", "duplicate", "unresolved_ocr"
    ] = "narrative_evidence"


class LayoutSection(Record):
    section_id: str
    heading_span_ids: list[str]
    heading_verbatim: str
    heading_bbox: BBox
    scope_bbox: BBox
    boundary_basis: SectionBasis
    ambiguity: list[str] = Field(default_factory=list)


class SourceObservation(Record):
    observation_id: str
    section_id: str
    kind: ObservationKind
    number: int | None = None
    span_ids: list[str]
    verbatim_text: str
    source_bbox: BBox
    effective_period_quotes: list[str] = Field(default_factory=list)
    confidence: Literal["native_source_group", "ocr_only_unreviewed"]
    ambiguity: list[str] = Field(default_factory=list)
    interpretation: Literal["source_statement_not_executable_rule"] = (
        "source_statement_not_executable_rule"
    )
    cross_source_pairing: Literal["pending"] = "pending"


class ImageContext(Record):
    image_id: str
    page_number: int
    xref: int
    mask_xref: int | None = None
    placement_bbox: BBox
    transform: tuple[float, float, float, float, float, float]
    width_px: int
    height_px: int
    source_stream_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    paint_sequence_numbers: list[int] = Field(default_factory=list)
    native_object_refs: list[str] = Field(default_factory=list)
    native_placement_id: str | None = None
    native_paint_ids: list[str] = Field(default_factory=list)
    native_clip_association: Literal["unknown"] = "unknown"
    section_id: str | None = None
    heading_span_ids: list[str] = Field(default_factory=list)
    caption_span_ids: list[str] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)
    association_status: Literal["layout_associated", "ambiguous", "unscoped"] = "unscoped"
    association_confidence: Literal["strong_layout", "weak_layout", "unresolved"] = "unresolved"
    context_kind: ContextKind = "unknown"
    ambiguity: list[str] = Field(default_factory=list)
    geometry_claim: Literal["source_placement_only"] = "source_placement_only"
    feature_localization: Literal["not_established"] = "not_established"


class PageSemantics(Record):
    schema_version: Literal[1] = 1
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    page_number: int
    coordinate_system: Literal["unrotated_mupdf_points"] = "unrotated_mupdf_points"
    page_bbox: BBox
    source_lines: list[SourceLine]
    sections: list[LayoutSection]
    observations: list[SourceObservation]
    image_contexts: list[ImageContext]
    discarded_figure_count: int
    native_inventory_sha256: str | None = None
    native_inventory_status: Literal["not_supplied", "source_checked_and_joined"] = "not_supplied"
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Layout association is an evidence link, not a semantic or authenticity verdict.",
            "Numbered callouts are not located on card pixels without leader/label evidence.",
            "Temporal wording stays verbatim; no exact issue-date interval is inferred.",
            "No OCR output is promoted into a credential field or a normalized field zone.",
            "Cross-page/source design pairing requires a separate grounded semantic review.",
        ]
    )


def rect(values: Sequence[float]) -> BBox:
    return float(values[0]), float(values[1]), float(values[2]), float(values[3])


def normalized_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[\w]+", value))


def area(box: BBox) -> float:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def intersection(a: BBox, b: BBox) -> float:
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def union(boxes: Sequence[BBox]) -> BBox:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def contains_center(outer: BBox, inner: BBox) -> bool:
    x, y = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] <= x <= outer[2] and outer[1] <= y < outer[3]


def source_line(
    page_number: int, block_index: int, line_index: int, raw: dict[str, Any]
) -> SourceLine:
    spans = raw["spans"]
    text = "".join(s["text"] for s in spans)
    weights = [max(1, len(s["text"].strip())) for s in spans]
    bold_weight = sum(w for s, w in zip(spans, weights, strict=True) if int(s["flags"]) & 16)
    return SourceLine(
        span_id=f"p{page_number}-b{block_index}-l{line_index}",
        page_number=page_number,
        block_index=block_index,
        line_index=line_index,
        bbox=rect(raw["bbox"]),
        verbatim_text=text,
        method="pdf_text",
        font_size=max(float(s["size"]) for s in spans),
        bold_fraction=bold_weight / max(1, sum(weights)),
    )


def native_run(raw: dict[str, Any], run_id: str, trace: list[dict[str, Any]]) -> NativeTextRun:
    bbox = rect(raw["bbox"])
    sequences = [
        int(item["seqno"])
        for item in trace
        if intersection(bbox, rect(item["bbox"]))
        / max(1, min(area(bbox), area(rect(item["bbox"]))))
        >= 0.6
    ]
    return NativeTextRun(
        run_id=run_id,
        verbatim_text=raw["text"],
        bbox=bbox,
        font_name=raw["font"],
        font_size=float(raw["size"]),
        font_flags=int(raw["flags"]),
        color=int(raw["color"]),
        origin=(float(raw["origin"][0]), float(raw["origin"][1])),
        paint_sequence_numbers=sequences,
    )


def native_lines(page: Any, page_number: int) -> list[SourceLine]:
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    result = []
    trace = page.get_texttrace()
    for block_index, block in enumerate(page.get_text("dict", flags=flags)["blocks"]):
        for line_index, raw in enumerate(block.get("lines", [])):
            if not any(s["text"].strip() for s in raw["spans"]):
                continue
            line = source_line(page_number, block_index, line_index, raw)
            line.native_runs = [
                native_run(run, f"{line.span_id}-r{index}", trace)
                for index, run in enumerate(raw["spans"])
            ]
            if line.bbox[1] > page.cropbox.height * 0.93:
                line.disposition = "page_furniture"
            result.append(line)
    return result


def transcription_duplicate(ocr: SourceLine, native: SourceLine) -> bool:
    overlap = intersection(ocr.bbox, native.bbox) / max(1, min(area(ocr.bbox), area(native.bbox)))
    a, b = normalized_text(ocr.verbatim_text), normalized_text(native.verbatim_text)
    # Containment tolerates an OCR omission of a list marker, not a changed number or word.
    return overlap >= 0.45 and bool(a) and (a == b or f" {a} " in f" {b} ")


def merge_ocr(
    native: list[SourceLine], ocr_blocks: Sequence[TextBlock], images: list[ImageContext]
) -> list[SourceLine]:
    result = list(native)
    for index, block in enumerate(ocr_blocks):
        line = SourceLine(
            span_id=f"p{block.page_number}-ocr-{index}",
            page_number=block.page_number,
            block_index=-(index + 1),
            line_index=0,
            bbox=block.bbox,
            verbatim_text=block.text,
            method="local_ocr",
            ocr_confidence=block.ocr_confidence,
            disposition="unresolved_ocr",
        )
        duplicate = next((n for n in native if transcription_duplicate(line, n)), None)
        if duplicate is not None:
            line.duplicate_of = duplicate.span_id
            line.disposition = "duplicate"
        elif any(contains_center(image.placement_bbox, line.bbox) for image in images):
            line.disposition = "image_transcription"
        result.append(line)
    return result


def placed_images(page: Any, page_number: int) -> tuple[list[ImageContext], int]:
    masks = {int(item[0]): int(item[1]) for item in page.get_images(full=True)}
    result, excluded = [], 0
    paint_log = page.get_bboxlog()
    raw_images = sorted(
        page.get_image_info(xrefs=True), key=lambda item: (item["bbox"][1], item["bbox"][0])
    )
    for index, item in enumerate(raw_images):
        bbox = rect(item["bbox"])
        if min(item["width"], item["height"]) < 32 or area(bbox) < 400:
            excluded += 1
            continue
        xref = int(item["xref"])
        stream_hash = (
            hashlib.sha256(page.parent.xref_stream_raw(xref)).hexdigest() if xref else None
        )
        result.append(
            ImageContext(
                image_id=f"p{page_number}-xref{xref}-placement{index}",
                page_number=page_number,
                xref=xref,
                mask_xref=masks.get(xref) or None,
                placement_bbox=bbox,
                transform=matrix6(item["transform"]),
                width_px=int(item["width"]),
                height_px=int(item["height"]),
                source_stream_sha256=stream_hash,
                paint_sequence_numbers=[
                    sequence
                    for sequence, log in enumerate(paint_log)
                    if log[0] == "fill-image"
                    and max(abs(a - b) for a, b in zip(bbox, log[1], strict=True)) < 0.01
                ],
                native_object_refs=[f"xref:{xref}"] if xref else [],
            )
        )
    return result, excluded


def matrix6(values: Sequence[float]) -> tuple[float, float, float, float, float, float]:
    return (*rect(values), float(values[4]), float(values[5]))


def heading_basis(line: SourceLine, body_size: float, page_width: float) -> SectionBasis | None:
    text = line.verbatim_text.strip().removesuffix(r"\n").strip()
    if line.disposition != "narrative_evidence" or line.bold_fraction < 0.8:
        return None
    if re.match(r"^\d+[.)]", text) or len(text) < 5:
        return None
    if (line.font_size or 0) > body_size + 0.7 or text.endswith(":"):
        return "typographic_heading"
    if line.bbox[2] - line.bbox[0] > page_width * 0.65:
        return "emphasized_paragraph"
    return None


def heading_groups(
    lines: list[SourceLine], width: float
) -> list[tuple[list[SourceLine], SectionBasis]]:
    body_size = median(
        [line.font_size or 11 for line in lines if line.disposition == "narrative_evidence"] or [11]
    )
    result: list[tuple[list[SourceLine], SectionBasis]] = []
    candidates = [(line, heading_basis(line, body_size, width)) for line in lines]
    for line, basis in sorted(candidates, key=lambda row: (row[0].bbox[1], row[0].bbox[0])):
        if basis is None:
            continue
        if result and adjacent_heading_line(result[-1][0][-1], line):
            result[-1][0].append(line)
        else:
            result.append(([line], basis))
    return result


def adjacent_heading_line(previous: SourceLine, current: SourceLine) -> bool:
    gap = current.bbox[1] - previous.bbox[3]
    return (
        previous.block_index == current.block_index
        and abs(previous.bbox[0] - current.bbox[0]) < 8
        and gap < 8
    )


def section_scope(
    index: int, groups: list[tuple[list[SourceLine], SectionBasis]], page_box: BBox
) -> BBox:
    own = union([line.bbox for line in groups[index][0]])
    left, right, bottom = page_box[0], page_box[2], page_box[3] * 0.93
    for other_index, (lines, _) in enumerate(groups):
        if other_index == index:
            continue
        other = union([line.bbox for line in lines])
        left, right, bottom = scope_with_neighbor((left, right, bottom), own, other)
    return left, own[1], right, bottom


def scope_with_neighbor(
    bounds: tuple[float, float, float], own: BBox, other: BBox
) -> tuple[float, float, float]:
    left, right, bottom = bounds
    if abs(other[1] - own[1]) >= 16:
        if other[1] > own[3] and other[0] < right and other[2] > left:
            bottom = min(bottom, other[1])
        return left, right, bottom
    if other[0] > own[2]:
        right = min(right, (own[2] + other[0]) / 2)
    elif other[2] < own[0]:
        left = max(left, (other[2] + own[0]) / 2)
    return left, right, bottom


def build_sections(lines: list[SourceLine], page_box: BBox) -> list[LayoutSection]:
    groups = heading_groups(lines, page_box[2] - page_box[0])
    result = []
    for index, (heading_lines, basis) in enumerate(groups):
        result.append(
            LayoutSection(
                section_id=f"p{heading_lines[0].page_number}-section{index}",
                heading_span_ids=[line.span_id for line in heading_lines],
                heading_verbatim="\n".join(line.verbatim_text for line in heading_lines),
                heading_bbox=union([line.bbox for line in heading_lines]),
                scope_bbox=section_scope(index, groups, page_box),
                boundary_basis=basis,
            )
        )
    return result


def matching_sections(box: BBox, sections: list[LayoutSection]) -> list[LayoutSection]:
    return [section for section in sections if contains_center(section.scope_bbox, box)]


def group_observation_lines(lines: list[SourceLine]) -> list[list[SourceLine]]:
    groups: list[list[SourceLine]] = []
    for line in sorted(lines, key=lambda value: (value.bbox[1], value.bbox[0])):
        # Native PDF block boundaries provide paragraph grouping; list starts remain distinct.
        new_item = bool(re.match(r"^\s*(?:\d+[.)]|[•●])", line.verbatim_text))
        if groups and not new_item and groups[-1][-1].block_index == line.block_index:
            groups[-1].append(line)
        else:
            groups.append([line])
    return groups


def observation_kind(text: str) -> tuple[ObservationKind, int | None]:
    numbered = re.match(r"^\s*(\d+)[.)]\s*", text)
    if numbered:
        return "numbered_callout", int(numbered[1])
    if text.lstrip().startswith(("•", "●")):
        return "bullet_statement", None
    if period_quotes(text):
        return "applicability_statement", None
    return "narrative", None


def period_quotes(text: str) -> list[str]:
    # Detect quoted temporal wording only; do not infer numeric date boundaries.
    return (
        [text]
        if re.search(
            r"\b(?:beginning|begining|issued|valid until|prior to|after|before)\b", text, re.I
        )
        else []
    )


def observations_for_section(
    section: LayoutSection, lines: list[SourceLine]
) -> list[SourceObservation]:
    heading = set(section.heading_span_ids)
    eligible = [
        line
        for line in lines
        if line.span_id not in heading
        and line.disposition == "narrative_evidence"
        and contains_center(section.scope_bbox, line.bbox)
    ]
    result = []
    # An emphasized temporal paragraph is source evidence as well as a layout boundary.
    if section.boundary_basis == "emphasized_paragraph" or period_quotes(section.heading_verbatim):
        eligible = [line for line in lines if line.span_id in heading] + eligible
    for index, group in enumerate(group_observation_lines(eligible)):
        text = "\n".join(line.verbatim_text for line in group)
        kind, number = observation_kind(text)
        result.append(
            SourceObservation(
                observation_id=f"{section.section_id}-observation{index}",
                section_id=section.section_id,
                kind=kind,
                number=number,
                span_ids=[line.span_id for line in group],
                verbatim_text=text,
                source_bbox=union([line.bbox for line in group]),
                effective_period_quotes=period_quotes(text),
                confidence="native_source_group",
            )
        )
    return result


def context_kind(section: LayoutSection, observations: list[SourceObservation]) -> ContextKind:
    text = normalized_text(
        section.heading_verbatim + " " + " ".join(o.verbatim_text for o in observations)
    )
    if any(
        phrase in text
        for phrase in (
            "professional and business",
            "business account",
            "secureaccess",
            "saw account",
        )
    ):
        return "administrative_interface"
    if any(
        phrase in text
        for phrase in (
            "driver s license",
            "driver license",
            "id cards",
            "id driver",
            "temporary license",
        )
    ):
        return "credential_reference"
    return "unknown"


def bind_image(
    image: ImageContext, sections: list[LayoutSection], observations: list[SourceObservation]
) -> ImageContext:
    matches = matching_sections(image.placement_bbox, sections)
    if len(matches) != 1:
        image.association_status = "ambiguous" if matches else "unscoped"
        image.ambiguity.append(
            "No unique typographic section contains this image placement center."
        )
        return image
    section = matches[0]
    grouped = [
        observation for observation in observations if observation.section_id == section.section_id
    ]
    image.section_id = section.section_id
    image.heading_span_ids = section.heading_span_ids
    image.observation_ids = [observation.observation_id for observation in grouped]
    image.association_status = "layout_associated"
    image.association_confidence = "strong_layout"
    image.context_kind = context_kind(section, grouped)
    image.ambiguity.extend(
        [
            "Section layout is associated; image-to-callout leader endpoints remain unresolved.",
            "Narrative comparison is not proof of identical printed field geometry.",
        ]
    )
    return image


def analyze_page(
    page: Any,
    *,
    source_sha256: str,
    page_number: int,
    ocr_blocks: Sequence[TextBlock] = (),
    native_inventory: Mapping[str, Any] | None = None,
) -> PageSemantics:
    if any(block.page_number != page_number for block in ocr_blocks):
        raise ValueError("OCR source page does not match the native PDF page")
    images, excluded = placed_images(page, page_number)
    lines = merge_ocr(native_lines(page, page_number), ocr_blocks, images)
    # Native positions use the unrotated cropped page with a zero origin.
    box = (0.0, 0.0, float(page.cropbox.width), float(page.cropbox.height))
    sections = build_sections(lines, box)
    observations = [
        observation
        for section in sections
        for observation in observations_for_section(section, lines)
    ]
    result = PageSemantics(
        source_sha256=source_sha256,
        page_number=page_number,
        page_bbox=box,
        source_lines=lines,
        sections=sections,
        observations=observations,
        image_contexts=[bind_image(image, sections, observations) for image in images],
        discarded_figure_count=excluded,
    )
    if native_inventory is not None:
        join_native_inventory(result, native_inventory)
    return result


def same_box(a: Sequence[float], b: Sequence[float]) -> bool:
    return (
        len(a) == len(b) and max(abs(float(x) - float(y)) for x, y in zip(a, b, strict=True)) < 0.01
    )


def join_native_image(image: ImageContext, inventory: Mapping[str, Any]) -> None:
    matches = [
        row
        for row in inventory["images"]
        if row["xref"] == image.xref and same_box(row["placement_bbox"], image.placement_bbox)
    ]
    if len(matches) != 1:
        image.ambiguity.append(
            "Native inventory placement join is unresolved or repeated at identical bounds."
        )
        return
    native = matches[0]
    objects = {row["object_id"]: row for row in inventory["objects"]}
    obj = objects.get(native["object_id"])
    if obj and obj.get("raw_stream_sha256") != image.source_stream_sha256:
        raise ValueError("Native image stream hash does not match the actual PDF source object")
    image.native_placement_id = native["placement_id"]
    image.native_paint_ids = native["paint_ids"]
    image.native_object_refs = [native["object_id"]] if native["object_id"] else []
    image.ambiguity.append(
        "Active clipping and Form invocation occurrence association remain unknown."
    )


def join_native_text(line: SourceLine, inventory: Mapping[str, Any]) -> None:
    for run in line.native_runs:
        run.native_text_ids = [
            text["text_id"]
            for text in inventory["text_runs"]
            if intersection(run.bbox, rect(text["bbox"]))
            / max(1, min(area(run.bbox), area(rect(text["bbox"]))))
            >= 0.6
        ]


def join_native_inventory(page: PageSemantics, inventory: Mapping[str, Any]) -> None:
    if (
        inventory["source_sha256"] != page.source_sha256
        or inventory["page_number"] != page.page_number
    ):
        raise ValueError("Native inventory source hash or page identity does not match")
    if inventory["coordinate_system"] != page.coordinate_system:
        raise ValueError("Native inventory coordinate system does not match")
    for image in page.image_contexts:
        join_native_image(image, inventory)
    for line in page.source_lines:
        join_native_text(line, inventory)
    page.native_inventory_sha256 = hashlib.sha256(
        json.dumps(dict(inventory), sort_keys=True).encode()
    ).hexdigest()
    page.native_inventory_status = "source_checked_and_joined"


def analyze_document(
    path: Path,
    page_numbers: Sequence[int],
    ocr_by_page: dict[int, list[TextBlock]] | None = None,
    native_inventory_by_page: dict[int, dict[str, Any]] | None = None,
) -> list[PageSemantics]:
    path = managed_path(path)
    with path.open("rb") as source:
        checksum = hashlib.file_digest(source, "sha256").hexdigest()
    with pymupdf.open(path) as document:
        return [
            analyze_page(
                document[number - 1],
                source_sha256=checksum,
                page_number=number,
                ocr_blocks=(ocr_by_page or {}).get(number, []),
                native_inventory=(native_inventory_by_page or {}).get(number),
            )
            for number in page_numbers
        ]


def audit_counts(pages: Sequence[PageSemantics]) -> dict[str, int]:
    dispositions = Counter(line.disposition for page in pages for line in page.source_lines)
    return {
        "pages": len(pages),
        "placed_figures": sum(len(page.image_contexts) for page in pages),
        "grouped_observations": sum(len(page.observations) for page in pages),
        "duplicate_transcriptions": dispositions["duplicate"],
        "unpromoted_image_transcriptions": dispositions["image_transcription"],
        "field_zones_generated": 0,
        "executable_rules_generated": 0,
    }
