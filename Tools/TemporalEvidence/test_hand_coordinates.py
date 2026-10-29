import unittest
import numpy as np
from PIL import Image, ImageOps
from hand_coordinates import source_point, source_transform


class HandCoordinateTests(unittest.TestCase):
    def test_all_exif_orientations_match_pillow_at_every_pixel_center(self):
        pixels = np.arange(15, dtype=np.uint8).reshape(3, 5)
        for orientation in range(1, 9):
            image = Image.fromarray(pixels)
            image.getexif()[274] = orientation
            upright = np.asarray(ImageOps.exif_transpose(image))
            transform = source_transform(5, 3, orientation)
            self.assertEqual(upright.shape, (transform['uprightHeight'], transform['uprightWidth']))
            for y, row in enumerate(upright):
                for x, value in enumerate(row):
                    sx, sy = source_point(dict(x=(x+.5)/upright.shape[1], y=(y+.5)/upright.shape[0]), transform)
                    self.assertAlmostEqual(sx, int(value) % 5 + .5)
                    self.assertAlmostEqual(sy, int(value) // 5 + .5)

    def test_off_image_coordinates_preserved_and_nonfinite_rejected(self):
        transform = source_transform(10, 20, 1)
        self.assertEqual(source_point(dict(x=-.2, y=1.1), transform), [-2, 22])
        with self.assertRaises(ValueError):
            source_point(dict(x=float('nan'), y=0), transform)
        for invalid in [0, 9, True]:
            with self.assertRaises(ValueError):
                source_transform(10, 20, invalid)
