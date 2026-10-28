"""Independent graph accounting and native-window topology review.

Windows are presentation only. No connections are added, no source samples are
changed, and bounded faces are never classified as physical document regions.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
import shapely
from shapely.geometry import shape, box

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Tools/CardBoundary'))
from native_input import load_native, verify_unchanged
from publication import publish_directory

WINDOWS = {
    'left-excursion': (460, 3860, 680, 4340),
    'bottom-left': (960, 4640, 1440, 4840),
    'bottom-middle': (2160, 4640, 2640, 4840),
    'bottom-right': (3360, 4670, 3840, 4870),
    'interior-printing': (2100, 2900, 2700, 3260),
    'interior-pattern': (2900, 4090, 3500, 4450),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()


def audit_graph(nodes, path_nodes, degrees, node_components):
    """Recompute incidence, connectivity and Euler rank independently of producer."""
    n = len(nodes)
    observed = np.bincount(path_nodes.ravel(), minlength=n)
    if not np.array_equal(observed, degrees):
        raise ValueError('Degree/incidence mismatch')
    graph = coo_matrix((np.ones(len(path_nodes), dtype=np.uint8),
                        (path_nodes[:, 0], path_nodes[:, 1])), shape=(n, n)).tocsr()
    count, components = connected_components(graph, directed=False)
    pairs = np.unique(np.column_stack((components, node_components)), axis=0)
    if len(pairs) != count or len(np.unique(node_components)) != count:
        raise ValueError('Component partition mismatch')
    vertices = np.bincount(components, minlength=count)
    edge_counts = np.bincount(components[path_nodes[:, 0]], minlength=count)
    ranks = edge_counts - vertices + 1
    if np.any(ranks < 0):
        raise ValueError('Invalid component cycle rank')
    return {
        'vertices': n, 'edges': len(path_nodes), 'connectedComponents': int(count),
        'endpoints': int(np.sum(degrees == 1)), 'junctions': int(np.sum(degrees >= 3)),
        'selfLoopPaths': int(np.sum(path_nodes[:, 0] == path_nodes[:, 1])),
        'cycleRank': int(ranks.sum()), 'cyclicComponents': int(np.sum(ranks > 0)),
        'acyclicComponents': int(np.sum(ranks == 0)),
        'incidenceVerified': True, 'componentPartitionVerified': True,
    }


def window_inventory(arrays, geometries, bounds):
    x0, y0, x1, y1 = bounds
    nodes = arrays['nodes']
    keep = ((nodes[:, 0] >= x0) & (nodes[:, 0] < x1) &
            (nodes[:, 1] >= y0) & (nodes[:, 1] < y1))
    degree = arrays['degrees'][keep]
    window = box(x0, y0, x1, y1)
    intersecting = [i for i, g in enumerate(geometries) if g.intersects(window)]
    contained = [i for i in intersecting if window.covers(geometries[i])]
    areas = np.array([geometries[i].area for i in contained])
    return {'boundsExclusive': list(bounds), 'nodes': int(keep.sum()),
            'endpoints': int(np.sum(degree == 1)), 'junctions': int(np.sum(degree >= 3)),
            'componentsAtNodes': int(len(np.unique(arrays['node_components'][keep]))),
            'facesIntersecting': len(intersecting), 'facesContained': len(contained),
            'containedFaceAreasSourcePixels2': {
                'min': float(areas.min()) if len(areas) else None,
                'median': float(np.median(areas)) if len(areas) else None,
                'max': float(areas.max()) if len(areas) else None},
            'faceIndicesIntersecting': intersecting}, keep, intersecting


def render(rgb, arrays, geometries, bounds, keep, face_indices):
    x0, y0, x1, y1 = bounds
    source = Image.fromarray(rgb[y0:y1, x0:x1])
    topology = source.copy()
    draw = ImageDraw.Draw(topology)
    p, offsets = arrays['path_points'], arrays['path_offsets']
    for a, b in zip(offsets[:-1], offsets[1:]):
        line = p[a:b]
        if (line[:, 0].max() < x0 or line[:, 0].min() >= x1 or
                line[:, 1].max() < y0 or line[:, 1].min() >= y1):
            continue
        draw.line([(float(x-x0), float(y-y0)) for x, y in line], fill=(180, 100, 220), width=1)
    # Display glyphs, not extra graph edges. Every node is retained in the data.
    for (x, y), d in zip(arrays['nodes'][keep], arrays['degrees'][keep]):
        if d == 1 or d >= 3:
            x, y = float(x-x0), float(y-y0)
            draw.ellipse((x-1, y-1, x+1, y+1), fill=(255, 215, 0) if d == 1 else (255, 55, 55))
    faces = source.copy()
    draw = ImageDraw.Draw(faces)
    for i in face_indices:
        g = geometries[i]
        for ring in [g.exterior, *g.interiors]:
            draw.line([(float(x-x0), float(y-y0)) for x, y in ring.coords], fill=(0, 190, 255), width=1)
    return source, topology, faces


def audit_line_coverage(points, offsets, path_points, path_offsets):
    original = shapely.MultiLineString([points[a:b] for a,b in zip(offsets[:-1],offsets[1:])
                if b-a>1 and np.any(points[a:b] != points[a])])
    derived = shapely.MultiLineString([path_points[a:b] for a,b in zip(path_offsets[:-1],path_offsets[1:])])
    difference = shapely.symmetric_difference(original, derived)
    if not difference.is_empty:
        raise ValueError('Noded linework differs from original geometry')
    return {'symmetricDifferenceEmpty': True, 'gapBridging': False}


def original_chain_endings(points, offsets):
    lengths = np.diff(offsets)
    eligible = lengths >= 3
    delta = points[offsets[:-1]].astype(np.int64) - points[offsets[1:]-1]
    squared = np.sum(delta*delta, axis=1)
    return {'singletonChains': int(np.sum(lengths == 1)),
            'chainsWithAtLeastThreePoints': int(eligible.sum()),
            'exactClosedChainsWithAtLeastThreePoints': int(np.sum(eligible & (squared == 0))),
            'distinctEndsOnePixelApart': int(np.sum(eligible & (squared == 1))),
            'distinctEndsDiagonalNeighbors': int(np.sum(eligible & (squared == 2))),
            'distinctEndsBeyondDiagonalNeighbor': int(np.sum(eligible & (squared > 2))),
            'endpointSquaredDistanceQuantiles': dict(zip(('min','median','q95','max'),
                map(float,np.quantile(squared[eligible],[0,.5,.95,1])))) if eligible.any() else {}}


def edge_density(points, mask):
    unique = np.unique(points, axis=0)
    inside = mask[unique[:, 1], unique[:, 0]] != 0
    inside_pixels = int(np.count_nonzero(mask))
    outside_pixels = int(mask.size - inside_pixels)
    return {'retainedPointCount': len(points), 'uniqueEdgePixelCount': len(unique),
            'inside': {'regionPixels': inside_pixels, 'uniqueEdgePixels': int(inside.sum()),
                       'density': float(inside.sum()/inside_pixels) if inside_pixels else None},
            'outside': {'regionPixels': outside_pixels, 'uniqueEdgePixels': int((~inside).sum()),
                        'density': float((~inside).sum()/outside_pixels) if outside_pixels else None}}


def evaluate(baseline, topology, edges, boundary, out):
    from Tools.CardTopology.dataset import load_dataset
    from Tools.CardEdges.dataset import load_dataset as load_edges
    from validate_dataset import validate_dataset
    baseline, topology, edges, boundary = map(Path, (baseline, topology, edges, boundary))
    rgb, _, hashes = load_native(baseline)
    manifest, arrays, regions, snapshots = load_dataset(topology, source_hashes=hashes)
    edge_manifest, edge_points, edge_offsets, _, edge_snapshots = load_edges(edges, hashes)
    if manifest['edgeManifestSHA256'] != sha(edge_snapshots['manifest.json']):
        raise ValueError('Topology edge lineage mismatch')
    line_audit = audit_line_coverage(edge_points, edge_offsets, arrays['path_points'], arrays['path_offsets'])
    boundary_manifest = validate_dataset(boundary, baseline)
    mask_bytes = (boundary/'mask.png').read_bytes()
    if sha(mask_bytes) != boundary_manifest['artifacts']['mask']['sha256']:
        raise ValueError('Boundary mask changed after admission')
    mask = np.asarray(Image.open(io.BytesIO(mask_bytes)))
    if mask.shape != rgb.shape[:2]:
        raise ValueError('Boundary mask dimensions mismatch')
    density = edge_density(edge_points, mask)
    density['boundaryId'] = boundary_manifest['boundaryId']
    density['edgeManifestSHA256'] = sha(edge_snapshots['manifest.json'])
    density['partition'] = 'retained_grabcut_mask'
    graph = audit_graph(arrays['nodes'], arrays['path_nodes'], arrays['degrees'], arrays['node_components'])
    geometries = [shape(f['geometry']) for f in regions['features']]
    if any(not g.is_valid or g.is_empty or g.geom_type != 'Polygon' or g.area <= 0 for g in geometries):
        raise ValueError('Invalid bounded face')
    # Fully noded planar linework must satisfy Euler's bounded-face accounting.
    if graph['cycleRank'] != len(geometries):
        raise ValueError('Planar cycle rank differs from bounded face count')
    areas = np.array([g.area for g in geometries])
    report = {'schemaVersion': 1, 'type': 'id_cadastral_topology_review',
              'sourceHashes': hashes, 'topologyManifestSHA256': sha(snapshots['manifest.json']),
              'sourceSize': [rgb.shape[1], rgb.shape[0]], 'graphAudit': graph,
              'provisionalPartitionEdgeDensity': density, 'lineCoverageAudit': line_audit,
              'originalChainEndings': original_chain_endings(edge_points, edge_offsets),
              'boundedFaces': len(geometries),
              'faceAreaSourcePixels2Quantiles': dict(zip(('min', 'q25', 'median', 'q75', 'q95', 'max'),
                    map(float, np.quantile(areas, [0, .25, .5, .75, .95, 1])))) if len(areas) else {},
              'faceAreaAtMostOneSourcePixel2': int(np.sum(areas <= 1)),
              'physicalPerimeterSelected': False, 'regionSemanticsAssessed': False,
              'damageLocationRegistered': False, 'windows': {}}
    files, sections = {}, []
    for name, bounds in WINDOWS.items():
        record, keep, face_indices = window_inventory(arrays, geometries, bounds)
        report['windows'][name] = record
        for suffix, im in zip(('source', 'topology', 'faces'), render(rgb, arrays, geometries, bounds, keep, face_indices)):
            stream = io.BytesIO(); im.save(stream, format='PNG')
            files[name+'-'+suffix+'.png'] = stream.getvalue()
        sections.append('<section><h2>'+name+'</h2><p>'+str(record['endpoints'])+' endpoints; '+str(record['junctions'])+
                        ' junctions; '+str(record['facesContained'])+' bounded faces wholly in this window.</p><div>'+''.join(
                            '<figure><figcaption>'+s+'</figcaption><img src="'+name+'-'+s+'.png"></figure>'
                            for s in ('source', 'topology', 'faces'))+'</div></section>')
    files['report.html'] = ('''<!doctype html><meta charset="utf-8"><title>ID Cadastral topology audit</title>
<style>body{background:#171b1e;color:#eef;font:16px system-ui;margin:24px}section div{display:flex;gap:12px}figure{margin:0;width:33%}img{width:100%;image-rendering:pixelated}a{color:#9cf}</style>
<h1>ID Cadastral topology audit</h1><p>Native source crops; observed paths with yellow endpoints and red junctions; cyan bounded-face outlines.
Only presentation is cropped. No gaps are joined. Exact geometric crossings are graph junctions; adjacency alone is not.
Bounded faces are spatial enclosures, not material or semantic classifications. Marker glyphs are display symbols.
Damage location remains unregistered. Graph cycle rank and polygonized face count were checked independently.</p>
<a href="review.json">Full measurements and provenance</a>'''+''.join(sections)).encode()
    report['artifacts'] = {n: {'sha256': sha(b), 'bytes': len(b)} for n,b in files.items()}
    report['implementationSHA256'] = sha(Path(__file__).read_bytes())
    files['review.json'] = encode(report)
    verify_unchanged(baseline, hashes)
    for name, data in snapshots.items():
        if (topology/name).read_bytes() != data:
            raise ValueError('Topology changed during review')
    if (boundary/'mask.png').read_bytes() != mask_bytes:
        raise ValueError('Boundary mask changed during review')
    for name, data in edge_snapshots.items():
        if (edges/name).read_bytes() != data:
            raise ValueError('Edges changed during review')
    publish_directory(Path(out), files)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','topology','edges','boundary','out'):
        p.add_argument('--'+name, required=True)
    a = p.parse_args()
    r = evaluate(a.baseline, a.topology, a.edges, a.boundary, a.out)
    print(json.dumps({k:r[k] for k in ('graphAudit','boundedFaces','faceAreaSourcePixels2Quantiles')}, indent=2))
