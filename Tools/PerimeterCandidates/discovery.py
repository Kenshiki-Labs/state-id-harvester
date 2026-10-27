"""Prior-localized inventory of native observed transitions; no perimeter selection.

The quadrilateral supplies search locations only. Original chains and every point
remain in the admitted upstream dataset. Membership is recorded for ALL points,
including those outside the search corridors. Runs never join or move vertices.
"""
import numpy as np

SIDE_NAMES = ('top', 'right', 'bottom', 'left')


def _validate(points, offsets, quad, fraction):
    points = np.asarray(points)
    offsets = np.asarray(offsets)
    quad = np.asarray(quad, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or points.dtype.kind not in 'iu':
        raise ValueError('Expected integer native point indices')
    if offsets.ndim != 1 or offsets.dtype.kind not in 'iu' or not len(offsets):
        raise ValueError('Expected integer chain offsets')
    if offsets[0] != 0 or offsets[-1] != len(points) or np.any(offsets[1:] <= offsets[:-1]):
        raise ValueError('Invalid chain offsets')
    if np.any(points < 0):
        raise ValueError('Negative image indices')
    if quad.shape != (4, 2) or not np.isfinite(quad).all():
        raise ValueError('Expected four finite cyclic prior corners')
    sides = np.roll(quad, -1, axis=0) - quad
    cross = sides[:, 0] * np.roll(sides, -1, axis=0)[:, 1] - sides[:, 1] * np.roll(sides, -1, axis=0)[:, 0]
    if np.any(cross <= 0):
        raise ValueError('Expected convex clockwise image-coordinate prior')
    if isinstance(fraction, bool) or not np.isfinite(fraction) or fraction <= 0:
        raise ValueError('Expected positive finite corridor fraction')
    for a, b in zip(offsets[:-1], offsets[1:]):
        if np.any(np.abs(np.diff(points[a:b].astype(np.int64), axis=0)) > 1):
            raise ValueError('Disconnected native chain')
    return points, offsets, quad, sides


def discover(points, offsets, prior_quad, corridor_fraction):
    """Return {arrays, candidates, summary, prior, method} for explicit inputs.

    ``prior_quad`` uses pixel-edge coordinates in TL, TR, BR, BL order.
    ``points`` uses source pixel indices. A point's center is index + 0.5.
    Corridor membership is distance to the FINITE side <= its explicit width.
    This permits overlapping corner searches and keeps competing transitions.
    """
    points, offsets, quad, sides = _validate(points, offsets, prior_quad, corridor_fraction)
    lengths = np.linalg.norm(sides, axis=1)
    width = float(lengths.min() * corridor_fraction)
    centers = points.astype(np.float64) + .5
    tangents = sides / lengths[:, None]
    # Clockwise image-coordinate quad: left normal points toward its interior.
    normals = np.column_stack((-tangents[:, 1], tangents[:, 0]))
    membership = np.zeros((len(points), 4), dtype=np.bool_)
    candidates = []
    chain_sides = np.zeros((len(offsets)-1, 4), dtype=np.bool_)
    for side in range(4):
        delta = centers - quad[side]
        along = delta @ tangents[side]
        normal = delta @ normals[side]
        closest = quad[side] + np.clip(along, 0, lengths[side])[:, None] * tangents[side]
        distances = np.linalg.norm(centers-closest, axis=1)
        inside = distances <= width
        membership[:, side] = inside
        # Source-chain endpoints are mandatory breaks even for adjacent points.
        starts = inside & np.r_[True, ~inside[:-1]] if len(points) else inside.copy()
        stops = inside & np.r_[~inside[1:], True] if len(points) else inside.copy()
        if len(points):
            starts[offsets[:-1]] = inside[offsets[:-1]]
            stops[offsets[1:]-1] = inside[offsets[1:]-1]
        for start, stop in zip(np.flatnonzero(starts), np.flatnonzero(stops)+1):
            chain = int(np.searchsorted(offsets, start, side='right')-1)
            chain_sides[chain, side] = True
            p = centers[start:stop]
            a = along[start:stop]
            n = normal[start:stop]
            candidates.append({
                'candidateId': len(candidates), 'sideIndex': side, 'side': SIDE_NAMES[side],
                'sourceChainIndex': chain, 'sourcePointStart': int(start),
                'sourcePointStopExclusive': int(stop), 'pointCount': int(stop-start),
                'sourceEndpoints': [p[0].tolist(), p[-1].tolist()],
                'tangentialRangePixels': [float(a.min()), float(a.max())],
                'signedNormalRangePixels': [float(n.min()), float(n.max())],
                'tangentialSpanFraction': float((a.max()-a.min())/lengths[side]),
                'lengthSourcePixels': float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum()),
                'corridorMarginMinimumPixels': float((width-distances[start:stop]).min()),
                'continuesOutsideCorridorBefore': bool(start > offsets[chain]),
                'continuesOutsideCorridorAfter': bool(stop < offsets[chain+1]),
            })
    arrays = {
        'point_side_membership': membership,
        'side_index': np.array([c['sideIndex'] for c in candidates], dtype=np.int8),
        'source_chain': np.array([c['sourceChainIndex'] for c in candidates], dtype=np.int64),
        'source_start': np.array([c['sourcePointStart'] for c in candidates], dtype=np.int64),
        'source_stop': np.array([c['sourcePointStopExclusive'] for c in candidates], dtype=np.int64),
        'chain_side_membership': chain_sides,
    }
    shared = [{'sourceChainIndex': int(i), 'sides': np.flatnonzero(chain_sides[i]).tolist()}
              for i in np.flatnonzero(chain_sides.sum(axis=1) > 1)]
    return {
        'arrays': arrays, 'candidates': candidates,
        'prior': {'corners': quad.tolist(), 'sideNames': list(SIDE_NAMES),
                  'sideLengthsPixels': lengths.tolist(), 'inwardNormals': normals.tolist(),
                  'corridorFraction': float(corridor_fraction), 'corridorWidthPixels': width},
        'method': {'name': 'native_chain_finite_side_corridors', 'version': 1,
                   'priorRole': 'localization', 'pointStride': 1, 'simplification': False,
                   'gapBridging': False, 'candidateTruncation': False,
                   'completeness': 'within_prior_corridors', 'physicalSelection': 'unresolved'},
        'summary': {'inputPointCount': len(points), 'inputChainCount': len(offsets)-1,
                    'candidateCount': len(candidates),
                    'pointsInAnyCorridor': int(np.count_nonzero(membership.any(axis=1))),
                    'pointsOutsideAllCorridors': int(np.count_nonzero(~membership.any(axis=1))),
                    'pointsInMultipleCorridors': int(np.count_nonzero(membership.sum(axis=1)>1)),
                    'candidateCountBySide': [int(np.count_nonzero(arrays['side_index']==s)) for s in range(4)],
                    'sharedSourceChainsAcrossSides': shared},
    }
