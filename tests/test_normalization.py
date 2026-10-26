"""Adversarial admission and orientation tests against frozen retained transforms."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from state_id_harvester.normalization import (
    RECTIFIER_SHA256,
    BoundaryDecision,
    checked_corners,
    load_rectifier,
    normalize_card,
)

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/id1-rectifier-transforms.json").read_text()
)


class FrozenRectifier:
    """Actual retained outputs, with independent OpenCV point projection."""

    def __init__(self, fixture):
        self.fixture = fixture

    def derive_transform(self, corners, geometry, pixels_per_mm):
        assert pixels_per_mm == 50
        np.testing.assert_array_equal(corners, self.fixture["ordered"])
        assert geometry["coordinates"][0][0] == geometry["coordinates"][0][-1]
        matrix_fields = {
            "sourceToRectified",
            "rectifiedToSource",
            "sourceToCardMillimeters",
            "cardMillimetersToSource",
        }
        return {
            k: np.asarray(v) if k in matrix_fields else v
            for k, v in self.fixture["transform"].items()
        }

    def warp_matrix(self, edge):
        np.testing.assert_array_equal(edge, self.fixture["transform"]["sourceToRectified"])
        return np.asarray(self.fixture["center"])

    @staticmethod
    def project(matrix, points):
        return cv2.perspectiveTransform(np.asarray(points, np.float64)[None], matrix)[0]


@pytest.mark.parametrize("fixture", FIXTURES["cases"])
def test_native_corners_map_to_full_nominal_canvas_without_flipping(fixture):
    assert FIXTURES["rectifier_sha256"] == RECTIFIER_SHA256
    h, w = fixture["height"], fixture["width"]
    image = np.zeros((h, w, 3), np.uint8)
    image[: h // 2, : w // 2] = (20, 40, 60)
    image[: h // 2, w // 2 :] = (80, 100, 120)
    image[h // 2 :, w // 2 :] = (140, 160, 180)
    image[h // 2 :, : w // 2] = (200, 220, 240)
    before = image.copy()
    decision = BoundaryDecision(
        original_asset_sha256="a" * 64, corners=fixture["corners"], basis="visual_card_corners"
    )
    result, metadata = normalize_card(image, decision, FrozenRectifier(fixture))
    expected_w, expected_h = (2699, 4280) if h > w else (4280, 2699)
    assert result.shape == (expected_h, expected_w, 3)
    mapped = cv2.perspectiveTransform(
        np.asarray(fixture["corners"])[None], np.asarray(metadata["source_to_output_pixel_edges"])
    )[0]
    np.testing.assert_allclose(
        mapped, [[0, 0], [expected_w, 0], [expected_w, expected_h], [0, expected_h]], atol=0.001
    )
    for y, x, color in [
        (0.2, 0.2, (20, 40, 60)),
        (0.2, 0.8, (80, 100, 120)),
        (0.8, 0.8, (140, 160, 180)),
        (0.8, 0.2, (200, 220, 240)),
    ]:
        np.testing.assert_array_equal(result[int(y * expected_h), int(x * expected_w)], color)
    np.testing.assert_array_equal(image, before)
    assert metadata["warp_calls"] == 1
    assert metadata["physical_calibration"] is False
    assert metadata["annotation_removal"] is False
    inverse = np.asarray(metadata["output_to_source_pixel_edges"])
    np.testing.assert_allclose(
        inverse @ np.asarray(metadata["source_to_output_pixel_edges"]), np.eye(3), atol=1e-9
    )


@pytest.mark.parametrize(
    "corners",
    [
        [[0, 0], [100, 0], [100, 60], [0, 60], [0, 0]],
        [[0, 0], [100, 0], [100, 60]],
        [[0, 0], [100, 0], [float("nan"), 60], [0, 60]],
        [[0, 0], [100, 0], [float("inf"), 60], [0, 60]],
        [[-1, 0], [100, 0], [100, 60], [0, 60]],
        [[0, 0], [101, 0], [100, 60], [0, 60]],
        [[0, 0], [100, 60], [100, 0], [0, 60]],
        [[0, 0], [0, 60], [100, 60], [100, 0]],
        [[0, 0], [100, 0], [20, 20], [0, 60]],
        [[0, 0], [1, 0], [1, 1], [0, 1]],
        [[0, 0], [100, 0], [100, 0], [0, 60]],
        [[0], [100, 0], [100, 60], [0, 60]],
    ],
)
def test_invalid_or_escaping_boundaries_never_reach_warp(corners):
    with pytest.raises((ValueError, ValidationError)):
        decision = BoundaryDecision(
            original_asset_sha256="a" * 64, corners=corners, basis="visual_card_corners"
        )
        checked_corners(decision, 100, 60)


def test_untrusted_rectifier_never_executes(tmp_path):
    marker = tmp_path / "executed"
    implementation = tmp_path / "rectify.py"
    implementation.write_text(f"open({str(marker)!r}, 'w').write('executed')")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_rectifier(implementation)
    assert not marker.exists()
    alias = tmp_path / "alias.py"
    alias.symlink_to(implementation)
    with pytest.raises(ValueError, match="Invalid retained"):
        load_rectifier(alias)


def test_unknown_boundary_basis_and_unbound_hash_rejected():
    with pytest.raises(ValidationError):
        BoundaryDecision(
            original_asset_sha256="not-a-hash",
            corners=[[0.0, 0.0]] * 4,
            basis="inferred_from_aspect_ratio",
        )
