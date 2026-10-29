"""Review retained native edge candidates without selecting a physical boundary.

Windows are presentation/measurement regions from the prior diagnostics; they
never initialize, constrain, crop, or rerun the full-scene detector. Coverage
means an image-edge observation exists, not that a card perimeter was found.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'CardBoundary'))
from native_input import load_native, verify_unchanged
from publication import publish_directory


WINDOWS = {
    'left-excursion': (460, 3860, 680, 4340),
    'bottom-left': (960, 4640, 1440, 4840),
    'bottom-middle': (2160, 4640, 2640, 4840),
    'bottom-right': (3360, 4670, 3840, 4870),
    'top-middle': (2200, 2170, 2800, 2390),
    'right-middle': (4440, 3270, 4740, 3870),
}
PALETTE = ((255, 0, 255), (30, 230, 80), (100, 130, 255),
           (255, 230, 20), (230, 60, 140), (70, 230, 220))


def json_bytes(value):
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def longest_true_run(values):
    padded = np.r_[False, np.asarray(values, dtype=bool), False].astype(np.int8)
    changes = np.diff(padded)
    starts, ends = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
    return int(np.max(ends - starts)) if len(starts) else 0


def profile(points, offsets, bounds, axis):
    """Count every retained point and distinct chain per row/column in a window."""
    x0, y0, x1, y1 = bounds
    if axis not in (0, 1) or x1 <= x0 or y1 <= y0:
        raise ValueError('Invalid profile axis/window')
    start, end = (x0, x1) if axis == 0 else (y0, y1)
    count = np.zeros(end - start, np.int64)
    chain_count = np.zeros_like(count)
    records = []
    for index, (a, b) in enumerate(zip(offsets[:-1], offsets[1:])):
        chain = points[a:b]
        keep = ((chain[:, 0] >= x0) & (chain[:, 0] < x1) &
                (chain[:, 1] >= y0) & (chain[:, 1] < y1))
        local = chain[keep]
        if not len(local):
            continue
        positions = local[:, axis] - start
        count += np.bincount(positions, minlength=end - start)
        chain_count[np.unique(positions)] += 1
        # Contiguous stored-chain intervals, not geometrically joined fragments.
        padded = np.r_[False, keep, False].astype(np.int8)
        runs = int(np.count_nonzero(np.diff(padded) == 1))
        records.append({'chainIndex': index, 'pointsInWindow': len(local),
                        'storedRunsInWindow': runs,
                        'positionsCovered': len(np.unique(positions)),
                        'boundsPixelIndices': [int(local[:, 0].min()), int(local[:, 1].min()),
                                               int(local[:, 0].max()), int(local[:, 1].max())]})
    records.sort(key=lambda r: (-r['positionsCovered'], r['chainIndex']))
    result = {'boundsExclusive': list(bounds), 'axis': 'columns' if axis == 0 else 'rows',
              'positions': end - start, 'positionsWithoutEdges': int(np.sum(count == 0)),
              'longestEmptyRun': longest_true_run(count == 0),
              'positionsWithMultipleChains': int(np.sum(chain_count > 1)),
              'distinctChains': len(records), 'chains': records,
              'maxPointsAtPosition': int(count.max()),
              'maxChainsAtPosition': int(chain_count.max())}
    return result, count, chain_count


def png(image):
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def render_window(rgb, points, offsets, rings, bounds):
    x0, y0, x1, y1 = bounds
    source = Image.fromarray(rgb[y0:y1, x0:x1])
    edges = source.copy()
    draw = ImageDraw.Draw(edges)
    for index, (a, b) in enumerate(zip(offsets[:-1], offsets[1:])):
        chain = points[a:b]
        keep = ((chain[:, 0] >= x0) & (chain[:, 0] < x1) &
                (chain[:, 1] >= y0) & (chain[:, 1] < y1))
        # Draw every actual native edge pixel, never lines across chain gaps.
        local = chain[keep] - np.array([x0, y0])
        if len(local):
            draw.point([tuple(p) for p in local.tolist()], fill=PALETTE[index % len(PALETTE)])
    combined = edges.copy()
    draw = ImageDraw.Draw(combined)
    for ring in rings:
        draw.line([(x - x0 - 0.5, y - y0 - 0.5) for x, y in ring],
                  fill=(255, 139, 56), width=1)
    return source, edges, combined


def evaluate(base, edges, boundary, out):
    # Rasterio/Shapely are required for boundary admission, not profile helpers.
    from validate_dataset import validate_dataset
    # Avoid confusing CardEdges.dataset with CardBoundary.dataset on sys.path.
    sys.path.insert(0, str(HERE.parents[1]))
    from Tools.CardEdges.dataset import load_dataset
    base, edges, boundary, out = map(Path, (base, edges, boundary, out))
    rgb, _, source_hashes = load_native(base)
    manifest, points, offsets, chains, snapshots = load_dataset(edges, source_hashes)
    boundary_manifest = validate_dataset(boundary, base)
    geometry_bytes = (boundary / 'geometry.json').read_bytes()
    if sha(geometry_bytes) != boundary_manifest['boundaryId']:
        raise ValueError('Boundary changed after admission')
    rings = json.loads(geometry_bytes)['coordinates']
    report = {'schemaVersion': 1, 'type': 'id_cadastral_edge_review',
              'sourceHashes': source_hashes, 'edgeManifestSHA256': sha(snapshots['manifest.json']),
              'boundaryId': boundary_manifest['boundaryId'],
              'sourceSize': [rgb.shape[1], rgb.shape[0]],
              'chainCount': len(offsets) - 1, 'pointCount': len(points),
              'coverageMeaning': 'retained image-edge points in a diagnostic window',
              'physicalPerimeterSelected': False, 'damageLocationRegistered': False,
              'windows': {}, 'profiles': {}}
    files, arrays = {}, {}
    sections = []
    for name, bounds in WINDOWS.items():
        axis = 1 if name.startswith(('left', 'right')) else 0
        result, count, chain_count = profile(points, offsets, bounds, axis)
        report['windows'][name] = result
        arrays[name + '_point_counts'] = count
        arrays[name + '_chain_counts'] = chain_count
        for suffix, image in zip(('source', 'edges', 'comparison'),
                                 render_window(rgb, points, offsets, rings, bounds)):
            files[name + '-' + suffix + '.png'] = png(image)
        sections.append('<section><h2>' + name + '</h2><p>Source bounds ' + str(bounds) +
                        '. Distinct chains: ' + str(result['distinctChains']) +
                        '; positions without an edge: ' + str(result['positionsWithoutEdges']) +
                        '/' + str(result['positions']) + '.</p><div class="images">' +
                        ''.join('<figure><figcaption>' + s + '</figcaption><img src="' + name +
                                '-' + s + '.png"></figure>' for s in ('source', 'edges', 'comparison')) +
                        '</div></section>')
    for name, bounds, axis in (('left-registered-296', (460, 3953, 680, 4249), 1),
                               ('bottom-3300', (1000, 4600, 4300, 4900), 0)):
        result, count, chain_count = profile(points, offsets, bounds, axis)
        report['profiles'][name] = result
        arrays[name + '_point_counts'] = count
        arrays[name + '_chain_counts'] = chain_count
    stream = io.BytesIO()
    np.savez_compressed(stream, **arrays)
    files['profiles.npz'] = stream.getvalue()
    files['report.html'] = ('''<!doctype html><html><meta charset="utf-8"><title>ID Cadastral edge review</title>
<style>body{background:#171b1e;color:#eef;font:16px system-ui;margin:24px}.images{display:flex;gap:12px;align-items:start}figure{margin:0;max-width:33%}img{max-width:100%;image-rendering:pixelated}section{margin-bottom:32px}a{color:#aaf}</style>
<h1>ID Cadastral: native edge candidates</h1><p>Original source crops, all native detector pixels, then orange GrabCut overlay.
Colors identify chains modulo six; distinct chains can share a color. No candidate is selected as the physical perimeter.
Images retain native pixels; browser presentation may scale them. Pixel indices map to source centers at +0.5.
Coverage counts include print and shadow transitions. The owner-confirmed damage remains unregistered.</p>
<p><a href="review.json">Review JSON</a> · <a href="profiles.npz">Full row/column counts</a></p>''' +
                            ''.join(sections) + '</html>').encode()
    report['artifacts'] = {name: {'sha256': sha(data), 'bytes': len(data)} for name, data in files.items()}
    report['implementationSHA256'] = sha(Path(__file__).read_bytes())
    files['review.json'] = json_bytes(report)
    verify_unchanged(base, source_hashes)
    for name, data in snapshots.items():
        if (edges / name).read_bytes() != data:
            raise ValueError('Edge package changed during review')
    publish_directory(out, files)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('baseline', 'edges', 'boundary', 'out'):
        parser.add_argument('--' + argument, required=True)
    args = parser.parse_args()
    result = evaluate(args.baseline, args.edges, args.boundary, args.out)
    print(json.dumps({k: result[k] for k in ('chainCount', 'pointCount', 'profiles')}, indent=2))
