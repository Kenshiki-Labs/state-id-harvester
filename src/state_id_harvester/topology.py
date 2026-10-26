"""Native source-reference proposals with separate geometry utilities.

Scores are ranking heuristics, not calibrated probabilities. No proposal is an accepted
card boundary. Nominal millimeters are an ID-1 coordinate convention, not a measurement.
"""

from __future__ import annotations

from typing import Any, Literal

import cv2
import numpy as np
from numpy.typing import NDArray

from .models import BoundaryCandidate, NormalizedRegion, TextBlock
from .pdf_components import NativeComponentGroup, component_groups
from .pdf_objects import InventoryLimits, NativeImagePlacement, PageObjectInventory, inventory_page

ID1_RATIO = 85.60 / 53.98
FloatArray = NDArray[np.float32]
Method = Literal["image_placement", "vector_rectangle", "contour"]


def order_corners(points: FloatArray) -> FloatArray:
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    ordered = points[np.argsort(angles)]
    start = int(np.argmin(ordered.sum(axis=1)))
    return np.roll(ordered, -start, axis=0)


def shape(points: FloatArray) -> tuple[float, float, float]:
    width = float(
        (np.linalg.norm(points[1] - points[0]) + np.linalg.norm(points[2] - points[3])) / 2
    )
    height = float(
        (np.linalg.norm(points[3] - points[0]) + np.linalg.norm(points[2] - points[1])) / 2
    )
    ratio = max(width, height) / max(min(width, height), 1e-6)
    return width, height, abs(ratio / ID1_RATIO - 1)


def normalize_regions(
    corners: FloatArray,
    blocks: list[TextBlock],
    width_mm: float,
    height_mm: float,
) -> list[NormalizedRegion]:
    unit = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
    transform = cv2.getPerspectiveTransform(corners, unit)
    result: list[NormalizedRegion] = []
    for block in blocks:
        x0, y0, x1, y1 = block.bbox
        vertices = np.array([[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]], dtype=np.float32)
        mapped = cv2.perspectiveTransform(vertices, transform)[0]
        # Include only blocks wholly inside the proposed boundary. External callouts
        # remain in source text, never silently become on-card zones.
        if float(mapped.min()) < -0.005 or float(mapped.max()) > 1.005:
            continue
        u0, v0 = (float(x) for x in np.clip(mapped.min(axis=0), 0, 1))
        u1, v1 = (float(x) for x in np.clip(mapped.max(axis=0), 0, 1))
        result.append(
            NormalizedRegion(
                bbox_uv=(u0, v0, u1, v1),
                text=block.text,
                bbox_mm_nominal=(u0 * width_mm, v0 * height_mm, u1 * width_mm, v1 * height_mm),
                evidence_page_bbox=block.bbox,
            )
        )
    return result


def proposals(page: Any) -> list[tuple[Method, FloatArray, float]]:
    """Source-native image extents only; context qualification happens in detect.

    A rectangular vector/text panel or raster edge is not sufficient card evidence.
    Such objects remain in the native inventory instead of becoming crop proposals.
    """
    candidates: list[tuple[Method, FloatArray, float]] = []
    for info in page.get_image_info(xrefs=True):
        a, b, c, d, e, f = info["transform"]
        points = np.array(
            [[e, f], [a + e, b + f], [a + c + e, b + d + f], [c + e, d + f]], dtype=np.float32
        )
        candidates.append(("image_placement", order_corners(points), 0.65))
    return candidates


RankedProposal = tuple[float, Method, FloatArray, float, float, float]


def rank_proposals(page: Any) -> list[RankedProposal]:
    import pymupdf

    ranked: list[RankedProposal] = []
    for method, corners, base in proposals(page):
        width, height, error = shape(corners)
        if min(width, height) < 35 or error > 0.12:
            continue
        area = abs(float(cv2.contourArea(corners)))
        if not 0.008 <= area / max(page.rect.get_area(), 1) <= 0.95:
            continue
        # Disallow off-page and degenerate boundaries.
        if any(not page.rect.contains(pymupdf.Point(float(p[0]), float(p[1]))) for p in corners):
            continue
        ranked.append((max(0.0, base - error), method, corners, width, height, error))
    return sorted(ranked, key=lambda candidate: -candidate[0])


def overlaps_existing(corners: FloatArray, accepted: list[FloatArray]) -> bool:
    area = abs(float(cv2.contourArea(corners)))
    for existing in accepted:
        overlap, _ = cv2.intersectConvexConvex(corners, existing)
        union = area + abs(float(cv2.contourArea(existing))) - float(overlap)
        if union > 0 and float(overlap) / union > 0.85:
            return True
    return False


def detect(
    page: Any,
    _blocks: list[TextBlock],
    page_number: int,
    *,
    inventory: PageObjectInventory | None = None,
    groups: list[NativeComponentGroup] | None = None,
    max_image_pixels: int = 40_000_000,
) -> list[tuple[BoundaryCandidate, bytes]]:
    """Emit original encoded image bytes, never a magnified page-render crop.

    Native text is kept as source context and overlapping components. It is not
    silently interpreted as a field zone or flattened into the underlying image.
    The legacy positional text-block argument remains intentionally unused;
    source text now comes from the native inventory rather than OCR field zones.
    """
    inventory = inventory or inventory_page(
        page,
        source_sha256="0" * 64,
        page_number=page_number,
        limits=InventoryLimits(max_image_pixels=max_image_pixels),
    )
    groups = (
        groups
        if groups is not None
        else component_groups(inventory, max_image_pixels=max_image_pixels)
    )
    images = {image.placement_id: image for image in inventory.images}
    output: list[tuple[BoundaryCandidate, bytes]] = []
    for group in groups:
        if group.status != "reference_candidate":
            continue
        image = images[group.image_placement_id]
        if image.width_px * image.height_px > max_image_pixels:
            continue
        encoded = page.parent.extract_image(image.xref)
        if not encoded:
            continue
        candidate = _native_candidate(image, group, page_number, len(output) + 1, encoded["ext"])
        output.append((candidate, encoded["image"]))
    return output


def _native_candidate(
    image: NativeImagePlacement,
    group: NativeComponentGroup,
    page_number: int,
    number: int,
    extension: str,
) -> BoundaryCandidate:
    a, b, c, d, e, f = image.transform
    corners = np.array(
        [[e, f], [a + e, b + f], [a + c + e, b + d + f], [c + e, d + f]], dtype=np.float32
    )
    width, height, error = shape(corners)
    nominal_width, nominal_height = (85.60, 53.98) if width >= height else (53.98, 85.60)
    return BoundaryCandidate(
        candidate_id=f"p{page_number}-c{number}",
        page_number=page_number,
        method="image_placement",
        page_bbox=image.placement_bbox,
        page_corners=[(float(p[0]), float(p[1])) for p in corners],
        aspect_ratio=width / max(height, 1e-9),
        aspect_error=error,
        score=max(0.0, 0.65 - error),
        crop_path="",
        text_regions=[],
        warnings=[
            "Native image extent; physical card perimeter and internal margins are unreviewed",
            "Original encoded image pixels; no resampling, rectification or annotation removal",
            "Masks and native overlays are separate evidence; this image is not a page composite",
            "Baked-in annotations, watermarks, clipping and credential identity require review",
            "Effective PPI describes PDF placement, not physical-card metric accuracy",
        ],
        nominal_width_mm=nominal_width,
        nominal_height_mm=nominal_height,
        boundary_scope="native_image_extent",
        crop_format=extension,
        native_provenance={
            "image_placement_id": image.placement_id,
            "image_object_id": image.object_id,
            "xref": image.xref,
            "group_id": group.group_id,
            "source_dimensions_px": [image.width_px, image.height_px],
            "output_dimensions_px": [image.width_px, image.height_px],
            "effective_ppi_at_pdf_placement": list(image.effective_ppi)
            if image.effective_ppi
            else None,
            "output_scale": [1.0, 1.0],
            "resampling": "none",
            "pixel_transform": "identity",
            "placement_transform": list(image.transform),
            "encoding": "original_extract_image_bytes",
            "mask_composition": "not_applied",
            "paint_ids": image.paint_ids,
            "clip_association": image.clip_association,
            "overlapping_paint_ids": group.overlapping_paint_ids,
            "later_overlapping_paint_ids": group.later_overlapping_paint_ids,
            "mask_object_ids": group.known_mask_object_ids,
            "annotation_content": group.annotation_content,
        },
    )
