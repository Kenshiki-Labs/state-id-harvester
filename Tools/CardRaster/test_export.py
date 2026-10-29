import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, PngImagePlugin

from export_geotiff import export, sha
from CardBoundary.publication import publish_directory


class ExportTests(unittest.TestCase):
    def fixture(self, root):
        base = root / 'source'
        base.mkdir()
        (base / 'front-original.heic').write_bytes(b'opaque retained original fixture')
        pixels = np.arange(32, dtype=np.uint8).reshape(2, 4, 4)
        info = PngImagePlugin.PngInfo()
        info.add(b'sRGB', b'\x00')
        Image.fromarray(pixels).save(base / 'front-rectified.png', pnginfo=info)
        geometry = {'outputPixelsPerMillimeter': 50, 'nominalWidthMillimeters': .08,
                    'nominalHeightMillimeters': .04, 'coordinateConvention': 'pixel_edges',
                    'distortionStatus': 'uncalibrated'}
        metadata = {'derivation': {'sourceSHA256': sha(base / 'front-original.heic'),
                    'outputSHA256': sha(base / 'front-rectified.png'),
                    'operation': 'id1Normalization', 'outputPixelWidth': 4,
                    'outputPixelHeight': 2, 'id1Geometry': geometry}}
        (base / 'front-geometry.json').write_text(json.dumps(metadata))
        return base, pixels

    def test_lossless_export_and_schema(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            root = Path(d)
            base, pixels = self.fixture(root)
            out = root / 'out'
            export(base, out)
            np.testing.assert_array_equal(np.array(Image.open(out / 'front-card.tif')), pixels)
            manifest = json.loads((out / 'manifest.json').read_text())
            self.assertEqual(manifest['schemaVersion'], 2)
            self.assertEqual(manifest['coordinateSystem']['type'], 'local_engineering')

    def test_destination_created_during_export_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            root = Path(d)
            base, _ = self.fixture(root)
            out = root / 'out'
            def raced_publish(destination, files):
                destination.mkdir()
                publish_directory(destination, files)
            with patch('export_geotiff.publish_directory', side_effect=raced_publish):
                with self.assertRaises(FileExistsError):
                    export(base, out)
            self.assertTrue(out.is_dir())
            self.assertEqual(list(out.iterdir()), [])

    def test_dangling_destination_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            out = root / 'out'
            out.symlink_to(root / 'missing')
            with self.assertRaisesRegex(ValueError, 'Output already exists'):
                export(root / 'source', out)


if __name__ == '__main__':
    unittest.main()
