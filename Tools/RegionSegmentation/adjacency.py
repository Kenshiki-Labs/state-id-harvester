"""Exact four-connected region topology and native pixel-interface statistics.

RAG supplies topology. Each horizontal/vertical label transition contributes one
shared unit pixel edge. Elevation on that interface is the arithmetic mean of
its two adjacent pixel elevations. Neither quantity is physical confidence.
"""
import numpy as np
from skimage.graph import RAG


def graph_records(labels, elevation, lab, texture):
    labels = np.asarray(labels)
    elevation, lab, texture = map(np.asarray, (elevation, lab, texture))
    if (labels.ndim != 2 or not np.issubdtype(labels.dtype, np.integer)
            or labels.size == 0 or np.any(labels <= 0)):
        raise ValueError('Labels must be a nonempty positive integer raster')
    if elevation.shape != labels.shape or texture.shape != labels.shape or lab.shape != (*labels.shape, 3):
        raise ValueError('Feature dimensions differ from labels')
    if not all(np.isfinite(a).all() for a in (elevation, lab, texture)):
        raise ValueError('Features must be finite')
    ids = np.unique(labels)
    if not np.array_equal(ids, np.arange(1, len(ids) + 1)):
        raise ValueError('Region labels must be consecutive starting at one')
    graph = RAG(labels, connectivity=1)
    flat = labels.ravel()
    counts = np.bincount(flat)
    means = []
    for channel in [lab[:, :, 0], lab[:, :, 1], lab[:, :, 2], texture]:
        total = np.bincount(flat, weights=channel.ravel(), minlength=len(counts))
        means.append(np.divide(total, counts, out=np.zeros_like(total), where=counts > 0))
    means = np.array(means).T
    nodes = [{'id': int(i), 'pixelCount': int(counts[i]), 'meanLab': means[i, :3].tolist(),
              'meanRelativeTexture': float(means[i, 3])} for i in ids]
    totals = {}
    # Aggregate every source pixel interface; no reduced representation of inputs.
    for a, b, ea, eb in [(labels[:, :-1], labels[:, 1:], elevation[:, :-1], elevation[:, 1:]),
                         (labels[:-1, :], labels[1:, :], elevation[:-1, :], elevation[1:, :])]:
        different = a != b
        first, second = a[different].astype(np.int64), b[different].astype(np.int64)
        if first.size == 0:
            continue
        pairs = np.column_stack((np.minimum(first, second), np.maximum(first, second)))
        unique, inverse, edge_counts = np.unique(pairs, axis=0, return_inverse=True, return_counts=True)
        values = (ea[different].astype(np.float64) + eb[different].astype(np.float64)) / 2.
        sums = np.bincount(inverse, weights=values, minlength=len(unique))
        for pair, count, summed in zip(unique, edge_counts, sums):
            key = tuple(map(int, pair))
            previous_count, previous_sum = totals.get(key, (0, 0.))
            totals[key] = previous_count + int(count), previous_sum + float(summed)
    topology = {tuple(sorted(map(int, pair))) for pair in graph.edges}
    if topology != set(totals):
        raise ValueError('RAG topology differs from actual shared pixel edges')
    edges = []
    for a, b in sorted(topology):
        count, summed = totals[(a, b)]
        delta = means[a] - means[b]
        edges.append({'regions': [a, b], 'meanBoundaryElevation': summed / count,
                      'sharedPixelEdgeCount': count, 'absoluteDeltaL': float(abs(delta[0])),
                      'deltaABMagnitude': float(np.linalg.norm(delta[1:3])),
                      'absoluteDeltaRelativeTexture': float(abs(delta[3]))})
    return {'regions': nodes, 'adjacencies': edges}
