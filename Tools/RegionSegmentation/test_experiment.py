"""Independent small-scene checks for the native region experiment."""
import unittest
import numpy as np
import experiment as subject
from adjacency import graph_records


class RegionExperimentTests(unittest.TestCase):
    def test_partition_assigns_every_pixel_and_keeps_basins_connected(self):
        y, x = np.mgrid[:31, :43]
        elevation = np.minimum((x-9)**2+(y-10)**2, (x-33)**2+(y-21)**2).astype(float)
        labels, count = subject.partition(elevation, 1.)
        self.assertEqual(labels.shape, elevation.shape)
        self.assertEqual(count, 2)
        self.assertTrue(np.all(labels > 0))
        self.assertEqual(set(np.unique(labels)), {1, 2})
        for value in np.unique(labels):
            _, connected = subject.ndi.label(labels == value, structure=subject.FOOTPRINT)
            self.assertEqual(connected, 1)
        repeated, _ = subject.partition(elevation, 1.)
        np.testing.assert_array_equal(labels, repeated)

    def test_nonfinite_elevation_is_rejected(self):
        for bad in [np.nan, np.inf, -np.inf]:
            with self.assertRaisesRegex(ValueError, 'Invalid elevation'):
                subject.partition(np.array([[0., bad], [1., 2.]]), .1)

    def test_four_connected_adjacency_excludes_diagonal_contacts(self):
        labels = np.array([[1, 2], [3, 4]], dtype=np.int32)
        graph = graph_records(labels, np.ones(labels.shape), np.zeros((2, 2, 3)), np.zeros(labels.shape))
        self.assertEqual({tuple(a['regions']) for a in graph['adjacencies']}, {(1,2),(1,3),(2,4),(3,4)})
        self.assertEqual(sum(n['pixelCount'] for n in graph['regions']), labels.size)

    def test_rag_matches_actual_side_sharing_pairs_at_junctions(self):
        elevation = np.random.default_rng(42).random((40,50))
        labels, _ = subject.partition(elevation,.08)
        expected = set()
        for left,right in [(labels[:,:-1],labels[:,1:]),(labels[:-1,:],labels[1:,:])]:
            expected.update(tuple(sorted((int(a),int(b))))
                            for a,b in zip(left.ravel(),right.ravel()) if a != b)
        graph = graph_records(labels,elevation,np.zeros((*labels.shape,3)),np.zeros(labels.shape))
        actual = {tuple(sorted(edge['regions'])) for edge in graph['adjacencies']}
        self.assertEqual(actual,expected)

    def test_shared_edge_counts_and_elevation_use_both_interface_pixels(self):
        labels = np.array([[1,1,2],[1,2,2]], dtype=np.int32)
        elevation = np.array([[0.,2.,4.],[6.,8.,10.]])
        graph = graph_records(labels,elevation,np.zeros((2,3,3)),np.zeros((2,3)))
        edge = graph['adjacencies'][0]
        self.assertEqual(edge['sharedPixelEdgeCount'],3)
        self.assertAlmostEqual(edge['meanBoundaryElevation'],(3.+7.+5.)/3.)

    def test_region_means_use_every_pixel(self):
        labels = np.array([[1, 1, 2], [1, 2, 2]], dtype=np.int32)
        lab = np.arange(18,dtype=float).reshape(2,3,3)
        texture = np.arange(6,dtype=float).reshape(2,3)
        graph = graph_records(labels, np.ones(labels.shape), lab, texture)
        for node in graph['regions']:
            mask = labels == node['id']
            self.assertEqual(node['pixelCount'], int(mask.sum()))
            np.testing.assert_allclose(node['meanLab'], lab[mask].mean(axis=0))
            self.assertAlmostEqual(node['meanRelativeTexture'], float(texture[mask].mean()))

    def test_one_region_has_no_adjacencies(self):
        labels = np.ones((4,5), dtype=np.int32)
        graph = graph_records(labels, np.ones(labels.shape), np.zeros((4,5,3)), np.zeros(labels.shape))
        self.assertEqual(graph['adjacencies'], [])
        self.assertEqual(graph['regions'][0]['pixelCount'], 20)

    def test_feature_derivation_preserves_input_samples_and_dimensions(self):
        rng = np.random.default_rng(734)
        rgb = rng.integers(0,256,size=(41,53,3),dtype=np.uint8)
        before = rgb.copy()
        rgb.setflags(write=False)
        elevations, lab, texture, info = subject.features(rgb, 45.)
        np.testing.assert_array_equal(rgb,before)
        self.assertEqual(lab.shape, rgb.shape)
        self.assertEqual(texture.shape, rgb.shape[:2])
        self.assertEqual(set(elevations), {'luminance','chroma_texture'})
        for elevation in elevations.values():
            self.assertEqual(elevation.shape,rgb.shape[:2])
            self.assertTrue(np.isfinite(elevation).all())
        self.assertAlmostEqual(info['derivativeSigmaSourcePixels'], 1.35)


if __name__ == '__main__':
    unittest.main()
