"""Native image component groups with evidence-bounded proposal or abstention.

The image boundary is an object extent, not a detected physical card perimeter.
Separately painted overlaps are retained as components, never erased from a render.
Page context qualifies only an unreviewed source-reference proposal. It cannot prove
that the pixels depict a credential, that a boundary is tight, or that artwork is clean.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field

from .models import Record
from .pdf_objects import NativeImagePlacement, PageObjectInventory

REFERENCE = re.compile(
    r"driver[’'s\s/-]*(?:license|licence)|identification card|\bID\s*(?:/driver|cards?)"
    r"|enhanced (?:cards?|licenses?)|credential (?:design|specimen)|license.{0,35}security",
    re.I,
)
ADMINISTRATIVE = re.compile(
    r"pay for a license|professional (?:and business )?licen[sc]|business account"
    r"|submitted applications|add administrator|pay fee button",
    re.I,
)


class NativeComponentGroup(Record):
    group_id: str
    image_placement_id: str
    image_object_id: str | None
    placement_bbox: tuple[float, float, float, float]
    status: Literal["reference_candidate", "abstained"]
    reasons: list[str]
    source_context_text_ids: list[str]
    overlapping_paint_ids: list[str]
    later_overlapping_paint_ids: list[str]
    known_mask_object_ids: list[str] = Field(default_factory=list)
    boundary_scope: Literal["native_image_extent"] = "native_image_extent"
    review_status: Literal["unreviewed"] = "unreviewed"
    annotation_content: Literal["not_determined"] = "not_determined"


def _overlap(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _reasons(
    image: NativeImagePlacement, context_ids: list[str], administrative: bool, max_image_pixels: int
) -> list[str]:
    reasons = []
    if administrative:
        reasons.append("Native source context describes an administrative interface")
    if not context_ids:
        reasons.append("No native source text identifies a credential reference context")
    if not image.xref:
        reasons.append("Inline image source bytes not individually addressable by xref")
    if image.width_px * image.height_px > max_image_pixels:
        reasons.append("Native image exceeds decoding pixel budget")
    a, b, c, d, _, _ = image.transform
    width, height = (a * a + b * b) ** 0.5, (c * c + d * d) ** 0.5
    ratio = max(width, height) / max(min(width, height), 1e-9)
    if min(width, height) < 35 or abs(ratio / (85.60 / 53.98) - 1) > 0.12:
        reasons.append("Native image extent is not compatible with an ID-1 reference proposal")
    if image.paint_association != "unique_bbox_match":
        reasons.append("Image paint association is unresolved or ambiguous")
    return reasons


def component_groups(
    inventory: PageObjectInventory, *, max_image_pixels: int, document_native_text: str = ""
) -> list[NativeComponentGroup]:
    """Retain every placement; only context-supported ID-1 extents get proposals."""
    context_ids = [run.text_id for run in inventory.text_runs if REFERENCE.search(run.text)]
    administrative = bool(ADMINISTRATIVE.search(document_native_text))
    administrative |= any(ADMINISTRATIVE.search(run.text) for run in inventory.text_runs)
    groups = []
    for image in inventory.images:
        overlapping = [
            paint
            for paint in inventory.paints
            if paint.paint_id not in image.paint_ids and _overlap(paint.bbox, image.placement_bbox)
        ]
        seqnos = [paint.seqno for paint in inventory.paints if paint.paint_id in image.paint_ids]
        later = [paint.paint_id for paint in overlapping if seqnos and paint.seqno > max(seqnos)]
        reasons = _reasons(image, context_ids, administrative, max_image_pixels)
        x0, y0, x1, y1 = inventory.page_bbox
        a, b, c, d, e, f = image.transform
        vertices = ((e, f), (a + e, b + f), (a + c + e, b + d + f), (c + e, d + f))
        if not all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in vertices):
            reasons.append("Native image placement extends beyond the visible page")
        groups.append(
            NativeComponentGroup(
                group_id=f"group:{image.placement_id}",
                image_placement_id=image.placement_id,
                image_object_id=image.object_id,
                placement_bbox=image.placement_bbox,
                status="abstained" if reasons else "reference_candidate",
                reasons=reasons
                or [
                    "Native image placement with credential-reference wording; requires review",
                    "Image extent, clipping, annotations and credential identity remain unverified",
                ],
                source_context_text_ids=context_ids,
                overlapping_paint_ids=[paint.paint_id for paint in overlapping],
                later_overlapping_paint_ids=later,
                known_mask_object_ids=_mask_ids(inventory, image.xref),
            )
        )
    return groups


def _mask_ids(inventory: PageObjectInventory, xref: int) -> list[str]:
    # Keep the source dictionary value intact; no content/resource interpreter here.
    obj = next((item for item in inventory.objects if item.xref == xref), None)
    if obj is None:
        return []
    return [
        f"xref:{value.split()[0]}"
        for key, (kind, value) in obj.mask_keys.items()
        if key in {"SMask", "Mask"} and kind == "xref"
    ]
