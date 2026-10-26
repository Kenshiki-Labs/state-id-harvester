"""ID-1 gate using the retained Cadastral rectifier, never guessed card boundaries."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field

from .paths import managed_path

RECTIFIER_SHA256 = "227a021f1923e9f0ec3434b1b581661f8cea133a65c10030111557909044d690"
ID1_SIZE = (4280, 2699)


class BoundaryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    original_asset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    corners: list[list[float]] = Field(min_length=4, max_length=4)
    basis: str = Field(pattern=r"^(visual_native_extent|visual_card_corners)$")


def load_rectifier(path: Path) -> Any:
    """Admit the exact retained implementation; never execute an unpinned module."""
    unresolved = path
    path = path.resolve()
    roots = [
        Path.cwd().resolve(),
        Path(tempfile.gettempdir()).resolve(),
        (Path.cwd().resolve().parent / "releases").resolve(),
        (Path.cwd().resolve().parent / "kenshiki-identity-sdk").resolve(),
    ]
    if not any(path.is_relative_to(root) for root in roots):
        raise ValueError("Retained rectifier is outside the managed host tools")
    if path.name != "rectify.py":
        raise ValueError("Expected the retained rectify.py implementation")
    if unresolved.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
        raise ValueError("Invalid retained rectifier file")
    if hashlib.sha256(path.read_bytes()).hexdigest() != RECTIFIER_SHA256:
        raise ValueError("Retained rectifier hash mismatch")
    specification = importlib.util.spec_from_file_location("cadastre_retained_rectifier", path)
    if specification is None or specification.loader is None:
        raise ValueError("Cannot load retained rectifier")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def checked_corners(decision: BoundaryDecision, width: int, height: int) -> NDArray[np.float64]:
    points = np.asarray(decision.corners, dtype=np.float64)
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError("Expected four finite pixel-edge corners")
    if np.any(points < 0) or np.any(points > [width, height]):
        raise ValueError("Card boundary escapes the original image")
    edges = np.roll(points, -1, axis=0) - points
    turns = edges[:, 0] * np.roll(edges[:, 1], -1) - edges[:, 1] * np.roll(edges[:, 0], -1)
    if not np.all(turns > 0) or np.min(np.linalg.norm(edges, axis=1)) < 8:
        raise ValueError("Expected a nondegenerate clockwise convex card boundary")
    area = float(cv2.contourArea(points.astype(np.float32)))
    if not math.isfinite(area) or area < 64:
        raise ValueError("Card boundary is degenerate")
    return points


def normalize_card(
    image: NDArray[np.uint8], decision: BoundaryDecision, rectifier: Any
) -> tuple[NDArray[np.uint8], dict[str, Any]]:
    """One retained source-pixel warp, then exact crop and optional quarter-turn."""
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ValueError("Normalization requires decoded uint8 BGR pixels")
    height, width = image.shape[:2]
    if width * height > 40_000_000:
        raise ValueError("Original image exceeds pixel budget")
    corners = checked_corners(decision, width, height)
    horizontal = float(np.linalg.norm(corners[1] - corners[0]))
    vertical = float(np.linalg.norm(corners[3] - corners[0]))
    portrait = vertical > horizontal
    # The retained rectifier's target is landscape. A cyclic corner order followed
    # by an exact quarter-turn preserves portrait orientation without resampling.
    ordered = np.roll(corners, -1, axis=0) if portrait else corners
    geometry = {"type": "Polygon", "coordinates": [[*ordered.tolist(), ordered[0].tolist()]]}
    transform = rectifier.derive_transform(ordered, geometry, pixels_per_mm=50)
    size = (transform["width"], transform["height"])
    if max(size) > 4300 or min(size) < 1 or size[0] * size[1] > 12_000_000:
        raise ValueError("Rectified output exceeds fixed ID-1 budget")
    edge = transform["sourceToRectified"]
    center = rectifier.warp_matrix(edge)
    padded = cv2.warpPerspective(
        image,
        center,
        size,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    offset = -np.asarray(transform["originCardMillimeters"]) * 50
    if not np.allclose(offset, np.rint(offset), rtol=0, atol=1e-8):
        raise ValueError("Nominal crop is not aligned to the retained grid")
    x, y = np.rint(offset).astype(int)
    nominal = padded[y : y + ID1_SIZE[1], x : x + ID1_SIZE[0]]
    if nominal.shape != (ID1_SIZE[1], ID1_SIZE[0], 3):
        raise ValueError("Incomplete nominal ID-1 output")
    crop_matrix = np.array([[1, 0, -x], [0, 1, -y], [0, 0, 1.0]])
    source_to_output = crop_matrix @ edge
    if portrait:
        nominal = np.rot90(nominal, -1)
        source_to_output = np.array([[0, -1, 2699], [1, 0, 0], [0, 0, 1]]) @ source_to_output
    mapped = rectifier.project(transform["sourceToCardMillimeters"], ordered)
    intended = np.array([[0, 0], [85.6, 0], [85.6, 53.98], [0, 53.98]])
    error = float(np.max(np.linalg.norm(mapped - intended, axis=1)))
    if error >= 1e-3:
        raise ValueError("Nominal millimeter corner mapping failed")
    return np.ascontiguousarray(nominal), {
        "status": "normalized_reference",
        "boundary_basis": decision.basis,
        "boundary_review": "visual_source_image_extent_only",
        "source_corners_pixel_edges": corners.tolist(),
        "source_to_output_pixel_edges": source_to_output.tolist(),
        "output_to_source_pixel_edges": np.linalg.inv(source_to_output).tolist(),
        "width_px": int(nominal.shape[1]),
        "height_px": int(nominal.shape[0]),
        "nominal_mm": [53.98, 85.6] if portrait else [85.6, 53.98],
        "pixels_per_mm": 50,
        "warp_calls": 1,
        "interpolation": "opencv_inter_linear",
        "rectifier_sha256": RECTIFIER_SHA256,
        "corner_max_error_mm": error,
        "physical_calibration": False,
        "annotation_removal": False,
    }


def read_decisions(path: Path) -> dict[str, BoundaryDecision]:
    unresolved = path
    path = managed_path(path)
    if unresolved.is_symlink() or not path.is_file() or path.stat().st_size > 4_000_000:
        raise ValueError("Invalid or oversized normalization manifest")
    document = json.loads(path.read_text())
    if document.get("schema_version") != 1 or not isinstance(document.get("decisions"), list):
        raise ValueError("Unsupported boundary decision registry")
    decisions = {}
    for raw in document["decisions"]:
        decision = BoundaryDecision.model_validate(raw)
        if decision.original_asset_sha256 in decisions:
            raise ValueError("Duplicate boundary decision")
        decisions[decision.original_asset_sha256] = decision
    return decisions


class NormalizationGate:
    """Reusable publication-preparation gate; missing boundaries remain pending."""

    def __init__(self, decisions: dict[str, BoundaryDecision], rectifier: Any) -> None:
        self.decisions = decisions
        self.rectifier = rectifier
        self.pending: list[dict[str, str]] = []
        self.completed = 0

    def prepare(
        self, image: NDArray[np.uint8], original_sha256: str, destination: Path
    ) -> tuple[NDArray[np.uint8], dict[str, Any]] | None:
        destination = managed_path(destination)
        decision = self.decisions.get(original_sha256)
        if decision is None:
            self.pending.append(
                {"original_asset_sha256": original_sha256, "reason": "card_boundary_required"}
            )
            return None
        if decision.original_asset_sha256 != original_sha256:
            raise ValueError("Boundary decision does not match the original asset")
        normalized, metadata = normalize_card(image, decision, self.rectifier)
        ok, encoded = cv2.imencode(".png", normalized, [cv2.IMWRITE_PNG_COMPRESSION, 3])
        if not ok:
            raise ValueError("Canonical ID-1 PNG encoding failed")
        data = encoded.tobytes()
        checksum = hashlib.sha256(data).hexdigest()
        directory = destination / "id1"
        if directory.is_symlink():
            raise ValueError("Canonical ID-1 directory must not be a symlink")
        directory.mkdir(exist_ok=True)
        path = directory / f"{checksum}.png"
        if path.is_symlink():
            raise ValueError("Canonical ID-1 artifact must not be a symlink")
        if path.exists() and path.read_bytes() != data:
            raise ValueError("Canonical ID-1 artifact conflicts with retained bytes")
        if not path.exists():
            path.write_bytes(data)
        self.completed += 1
        return normalized, {**metadata, "asset_sha256": checksum, "path": f"id1/{checksum}.png"}
