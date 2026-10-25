"""Deterministic boundary proposals, perspective crops, and coordinate-linked text.

Scores are ranking heuristics, not calibrated probabilities. No proposal is an accepted
card boundary. Nominal millimeters are an ID-1 coordinate convention, not a measurement.
"""

from __future__ import annotations

import math
from typing import Any, Literal

import cv2
import numpy as np
from numpy.typing import NDArray

from .models import BoundaryCandidate, NormalizedRegion, TextBlock

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
    """Combine image placements, vector rectangles, and bounded raster contours."""
    candidates: list[tuple[Method, FloatArray, float]] = []
    for info in page.get_image_info(xrefs=True):
        a, b, c, d, e, f = info["transform"]
        points = np.array(
            [[e, f], [a + e, b + f], [a + c + e, b + d + f], [c + e, d + f]], dtype=np.float32
        )
        candidates.append(("image_placement", order_corners(points), 0.65))
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "re":
                r = item[1]
                points = np.array(
                    [[r.x0, r.y0], [r.x1, r.y0], [r.x1, r.y1], [r.x0, r.y1]], dtype=np.float32
                )
                candidates.append(("vector_rectangle", points, 0.60))
    # Probe <= 2M pixels regardless of unusual PDF page dimensions.
    scale = min(120 / 72, math.sqrt(2_000_000 / max(page.rect.get_area(), 1)))
    import pymupdf

    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False, annots=False
    )
    raster = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    gray = cv2.cvtColor(raster, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:300]:
        if cv2.contourArea(contour) < 2_000:
            continue
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        points = polygon.reshape(4, 2).astype(np.float32)
        points[:, 0] = (points[:, 0] + pix.x) / scale
        points[:, 1] = (points[:, 1] + pix.y) / scale
        candidates.append(("contour", order_corners(points), 0.45))
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


def crop_proposal(
    page: Any, corners: FloatArray, width: float, height: float
) -> tuple[bytes, tuple[float, float, float, float]] | None:
    import pymupdf

    x0, y0 = (float(x) for x in corners.min(axis=0))
    x1, y1 = (float(x) for x in corners.max(axis=0))
    clip = pymupdf.Rect(x0, y0, x1, y1)
    scale = min(600 / 72, math.sqrt(4_000_000 / max(clip.get_area(), 1)))
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale),
        clip=clip,
        colorspace=pymupdf.csRGB,
        alpha=False,
        annots=False,
    )
    raster = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    crop_width = max(1, round(width * scale))
    crop_height = max(1, round(height * scale))
    src = corners * scale - np.array([pix.x, pix.y], dtype=np.float32)
    dst = np.array(
        [[0, 0], [crop_width - 1, 0], [crop_width - 1, crop_height - 1], [0, crop_height - 1]],
        dtype=np.float32,
    )
    crop = cv2.warpPerspective(
        raster, cv2.getPerspectiveTransform(src, dst), (crop_width, crop_height)
    )
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
    if not ok:
        return None
    return encoded.tobytes(), (x0, y0, x1, y1)


def boundary_candidate(
    proposal: RankedProposal,
    bbox: tuple[float, float, float, float],
    blocks: list[TextBlock],
    page_number: int,
    candidate_number: int,
) -> BoundaryCandidate:
    score, method, corners, width, height, error = proposal
    nominal_width, nominal_height = (85.60, 53.98) if width >= height else (53.98, 85.60)
    return BoundaryCandidate(
        candidate_id=f"p{page_number}-c{candidate_number}",
        page_number=page_number,
        method=method,
        page_bbox=bbox,
        page_corners=[(float(p[0]), float(p[1])) for p in corners],
        aspect_ratio=width / height,
        aspect_error=error,
        score=score,
        crop_path="",
        text_regions=normalize_regions(corners, blocks, nominal_width, nominal_height),
        warnings=[
            "Boundary is a proposal; specimen may be stretched, composite, or watermarked",
            "ID-1 millimeters are nominal; physical metric accuracy is unmeasured",
            "Orientation, credential identity, and internal layout require review",
        ],
        nominal_width_mm=nominal_width,
        nominal_height_mm=nominal_height,
    )


def detect(
    page: Any,
    blocks: list[TextBlock],
    page_number: int,
) -> list[tuple[BoundaryCandidate, bytes]]:
    output: list[tuple[BoundaryCandidate, bytes]] = []
    accepted_polygons: list[FloatArray] = []
    for proposal in rank_proposals(page):
        _, _, corners, width, height, _ = proposal
        if overlaps_existing(corners, accepted_polygons):
            continue
        # Preserve the original geometric deduplication order, even if encoding
        # later fails: another method must not silently replace that observation.
        accepted_polygons.append(corners)
        cropped = crop_proposal(page, corners, width, height)
        if cropped is None:
            continue
        png, bbox = cropped
        candidate = boundary_candidate(proposal, bbox, blocks, page_number, len(output) + 1)
        output.append((candidate, png))
        if len(output) == 12:
            break
    return output
