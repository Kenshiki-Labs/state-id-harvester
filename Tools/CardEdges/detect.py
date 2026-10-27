"""Native full-scene EdgeDrawing; no masks, resizing, line fits or chain simplification."""
import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from Tools.CardEdges.dataset import package
sys.path.append(str(Path(__file__).resolve().parents[1] / 'CardBoundary'))
from native_input import load_native, verify_unchanged
from json_contract import strict_json

CONFIG = Path(__file__).with_name('config.json')

def detect_native(rgb, config):
    if cv2.__version__ != '5.0.0' or version('opencv-contrib-python-headless') != '5.0.0.93':
        raise ValueError('Pinned OpenCV contrib 5.0.0.93 required')
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or min(rgb.shape[:2]) < 5:
        raise ValueError('Expected native RGB8 raster at least 5x5')
    if config['schemaVersion'] != 1 or config['parameters']['ScanInterval'] != 1 or config['parameters']['PFmode'] is not False:
        raise ValueError('Unsupported native detector configuration')
    cv2.setNumThreads(1)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    params = cv2.ximgproc.EdgeDrawing.Params()
    for name, value in config['parameters'].items():
        if not hasattr(params, name):
            raise ValueError('Unknown EdgeDrawing parameter: ' + name)
        setattr(params, name, value)
    detector = cv2.ximgproc.createEdgeDrawing()
    detector.setParams(params)
    detector.detectEdges(gray)
    segments = detector.getSegments()
    # OpenCV emits an empty placeholder for scenes without edges.
    segments = [np.asarray(segment, dtype='<i4').reshape(-1, 2) for segment in segments if len(segment)]
    points = np.concatenate(segments) if segments else np.empty((0, 2), dtype='<i4')
    offsets = np.concatenate((np.array([0], dtype='<i8'), np.cumsum([len(s) for s in segments], dtype='<i8')))
    return points, offsets

def run(base, out):
    started = time.monotonic()
    config_bytes = CONFIG.read_bytes()
    config = strict_json(config_bytes)
    source_code = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__), Path(__file__).with_name('dataset.py'), CONFIG]}
    rgb, _, hashes = load_native(base)
    before = hashlib.sha256(rgb.tobytes()).hexdigest()
    points, offsets = detect_native(rgb, config)
    if before != hashlib.sha256(rgb.tobytes()).hexdigest():
        raise ValueError('Detector modified source pixels')
    verify_unchanged(Path(base), hashes)
    h, w = rgb.shape[:2]
    manifest = {'schemaVersion': 1, 'type': 'id_cadastral_edge_candidates', 'sourceHashes': hashes,
                'coordinateSystem': {'type': 'image_pixel_indices', 'origin': 'top_left', 'xDirection': 'right', 'yDirection': 'down', 'width': w, 'height': h, 'pixelCenterOffset': [0.5, 0.5]},
                'method': 'opencv_ximgproc_EdgeDrawing', 'parameters': config['parameters'],
                'implementation': {'opencv': cv2.__version__, 'package': version('opencv-contrib-python-headless'), 'sourceCodeSHA256': source_code,
                                   'upstream': 'https://github.com/opencv/opencv_contrib/blob/5.0.0/modules/ximgproc/src/edge_drawing.cpp'},
                'processing': {'width': w, 'height': h, 'resize': False, 'crop': False, 'anchorScanInterval': 1,
                               'anchorBorderExcludedPixels': 2, 'grayscale': 'OpenCV COLOR_RGB2GRAY', 'gaussianKernel': [5, 5], 'chainSimplification': False, 'threads': 1},
                'elapsedSeconds': time.monotonic() - started, 'sourcePixelsUnchanged': True}
    result = package(out, manifest, points, offsets)
    print(json.dumps({'output': str(out), 'chains': result['chainCount'], 'points': result['pointCount'], 'seconds': result['elapsedSeconds']}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    run(args.baseline, args.output)
