"""Independent synthetic checks for contour-derived projective geometry."""
import copy
import unittest

import cv2
import numpy as np

from rectify import boundary_positions, derive_transform, fit_boundary, project, warp_matrix


def polygon(ring, holes=()):
    return {'type': 'Polygon', 'coordinates': [ring, *holes]}


RING = [[30, 40], [230, 40], [230, 160], [30, 160], [30, 40]]
CORNERS = np.array(RING[:4], dtype=float)


class RectificationTests(unittest.TestCase):
    def test_every_unit_boundary_segment_is_present(self):
        points = boundary_positions(polygon(RING))
        self.assertEqual(points.shape, (640, 2))
        self.assertEqual(len(np.unique(points, axis=0)), 640)
        expected = {(x + .5, 40.) for x in range(30, 230)}
        expected |= {(x + .5, 160.) for x in range(30, 230)}
        expected |= {(30., y + .5) for y in range(40, 160)}
        expected |= {(230., y + .5) for y in range(40, 160)}
        self.assertEqual(set(map(tuple, points)), expected)

    def test_holes_do_not_enter_exterior_fit(self):
        hole = [[80, 70], [80, 90], [100, 90], [100, 70], [80, 70]]
        geometry = polygon(RING, [hole])
        self.assertEqual(len(boundary_positions(geometry)), 640)
        model, _ = fit_boundary(geometry, CORNERS)
        np.testing.assert_allclose(model['corners'], CORNERS, atol=.01)

    def test_ring_start_and_winding_do_not_change_model(self):
        vertices = RING[:-1]
        for ring in [vertices, vertices[2:] + vertices[:2], list(reversed(vertices))]:
            with self.subTest(ring=ring):
                model, _ = fit_boundary(polygon(ring + [ring[0]]), CORNERS)
                np.testing.assert_allclose(model['corners'], CORNERS, atol=.01)

    def test_identity_warp_is_pixel_exact(self):
        pixels = np.random.default_rng(42).integers(0, 256, (37, 51, 3), dtype=np.uint8)
        matrix = warp_matrix(np.eye(3))
        result = cv2.warpPerspective(pixels, matrix, (51, 37), flags=cv2.INTER_LINEAR)
        np.testing.assert_array_equal(result, pixels)

    def test_warp_matrix_uses_edge_to_center_conjugation(self):
        edge = np.array([[1.7, .03, 7.], [-.05, 1.3, -4.], [.0002, -.0003, 1.]])
        centers = np.array([[0., 0.], [12., 21.], [107., 91.]])
        expected = project(edge, centers + .5) - .5
        np.testing.assert_allclose(project(warp_matrix(edge), centers), expected, atol=1e-10)

    def test_projective_roundtrip_and_nominal_corner_mapping(self):
        corners = np.array([[60., 40.], [250., 51.], [235., 180.], [30., 165.]])
        geometry = polygon([*corners.tolist(), corners[0].tolist()])
        transform = derive_transform(corners, geometry)
        card = np.array([[0., 0.], [85.6, 0.], [85.6, 53.98], [0., 53.98]])
        np.testing.assert_allclose(project(transform['sourceToCardMillimeters'], corners), card, atol=1e-5)
        probes = np.array([[80., 80.], [170., 125.], [30., 20.]])
        restored = project(transform['rectifiedToSource'], project(transform['sourceToRectified'], probes))
        np.testing.assert_allclose(restored, probes, atol=1e-8)

    def test_outward_protrusion_fits_output_extent(self):
        ring = [[30, 40], [110, 40], [110, 34], [120, 34], [120, 40],
                [230, 40], [230, 160], [30, 160], [30, 40]]
        geometry = polygon(ring)
        before = copy.deepcopy(geometry)
        transform = derive_transform(CORNERS, geometry)
        observed = project(transform['sourceToRectified'], np.array(ring, float))
        self.assertGreaterEqual(float(observed[:, 0].min()), 0.)
        self.assertGreaterEqual(float(observed[:, 1].min()), 0.)
        self.assertLessEqual(float(observed[:, 0].max()), transform['width'])
        self.assertLessEqual(float(observed[:, 1].max()), transform['height'])
        self.assertLess(transform['originCardMillimeters'][1], 0.)
        self.assertEqual(geometry, before)

    def test_local_dent_does_not_rewrite_contour(self):
        ring = [[30, 40], [115, 40], [115, 43], [125, 43], [125, 40],
                [230, 40], [230, 160], [30, 160], [30, 40]]
        geometry = polygon(ring)
        before = copy.deepcopy(geometry)
        model, _ = fit_boundary(geometry, CORNERS)
        # A ten-pixel-wide dent must not tilt the whole 200-pixel edge materially.
        np.testing.assert_allclose(model['corners'], CORNERS, atol=1.)
        self.assertEqual(geometry, before)

    def test_invalid_prior_is_rejected(self):
        for prior in [np.zeros((4, 2)), np.full((4, 2), np.nan),
                      np.array([[30, 40], [230, 160], [230, 40], [30, 160]], float)]:
            with self.subTest(prior=prior):
                with self.assertRaises(ValueError):
                    fit_boundary(polygon(RING), prior)

    def test_invalid_geometry_is_rejected(self):
        for geometry in [polygon([[0, 0], [20, 20], [20, 0], [0, 20], [0, 0]]),
                         polygon([[0, 0], [10, 0], [20, 0], [0, 0]])]:
            with self.subTest(geometry=geometry):
                with self.assertRaises(ValueError):
                    fit_boundary(geometry, CORNERS)


if __name__ == '__main__':
    unittest.main()
