"""Native scan evidence between discovered transitions; no material classifier.

RGB values are encoded channel values, not calibrated radiance. Every interval
references all original pixels in order; no resampling or smoothing is applied.
The caller binds the source raster and candidate geometry to package provenance.
"""
import numpy as np
from itertools import combinations, product


METHOD = {
    "name": "adjacent_transition_component_native_scan_profiles",
    "version": 1,
    "neighborhood": "inter_transition_depth_on_each_outer_side",
    "transitionPixels": "excluded_from_comparison_bands_retained_by_reference",
    "scanAxes": {"top": "y", "right": "x", "bottom": "y", "left": "x"},
    "texture": "mean_absolute_adjacent_channel_difference_along_scan",
    "selection": "unassessed",
}


def statistics(values):
    """All values contribute; black pixels have undefined chromaticity."""
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError("RGB profile must have shape (n, 3)")
    count = len(values)
    if not count:
        return {"pixelCount": 0}
    sums = values.sum(axis=1)
    valid = sums > 0
    chroma = values[valid] / sums[valid, None]
    return {
        "pixelCount": count,
        "meanRGB": values.mean(axis=0).tolist(),
        "stdRGB": values.std(axis=0).tolist(),
        "meanChannelIntensity": float(values.mean()),
        "stdMeanChannelIntensity": float(values.mean(axis=1).std()),
        "chromaticityPixelCount": int(valid.sum()),
        "meanChromaticity": chroma.mean(axis=0).tolist() if len(chroma) else None,
        "adjacentPairCount": max(0, count - 1),
        "meanAbsoluteAdjacentRGBDifference": np.abs(np.diff(values, axis=0)).mean(axis=0).tolist() if count > 1 else None,
    }


def compare_pair(rgb, axis, scan_index, first, second):
    """Ranges are inclusive native pixel indices ordered by increasing axis.

    Outputs retain requested and available bands separately. Partial bands may
    be inspected but never receive a complete comparison status.
    """
    if axis not in ("x", "y"):
        raise ValueError("axis must be x or y")
    if type(scan_index) is not int or not 0 <= scan_index < rgb.shape[0 if axis == "x" else 1]:
        raise ValueError("scan index outside source raster")
    line = rgb[scan_index, :, :] if axis == "x" else rgb[:, scan_index, :]
    a, b = first["range"], second["range"]
    if any(type(v) is not int for v in a + b) or not (0 <= a[0] <= a[1] < len(line) and 0 <= b[0] <= b[1] < len(line)):
        raise ValueError("transition ranges must be native pixel indices")
    depth = b[0] - a[1] - 1
    result = {"first": first, "second": second, "axis": axis,
              "scanIndex": int(scan_index), "betweenPixelCount": max(0, depth),
              "assessment": "unassessed", "bands": {}}
    if depth <= 0:
        result["status"] = "overlapping_transitions" if b[0] <= a[1] else "no_between_pixels"
        return result
    bands = {"before": (a[0] - depth, a[0]),
             "between": (a[1] + 1, b[0]),
             "after": (b[1] + 1, b[1] + 1 + depth)}
    complete = True
    for name, (start, stop) in bands.items():
        lo, hi = max(0, start), min(len(line), stop)
        complete = complete and start >= 0 and stop <= len(line)
        result["bands"][name] = {
            "requestedRange": [start, stop], "availableRange": [lo, hi],
            "rangeConvention": "start_inclusive_stop_exclusive",
            "statistics": statistics(line[lo:hi]),
        }
    result["status"] = "complete" if complete else "clipped_support"
    # Descriptive distances are not likelihoods and do not select an edge.
    if complete:
        middle = result["bands"]["between"]["statistics"]
        distances = {}
        for name in ("before", "after"):
            other = result["bands"][name]["statistics"]
            distances[name] = {
                "meanRGBEuclidean": float(np.linalg.norm(np.subtract(middle["meanRGB"], other["meanRGB"]))),
                "meanChromaticityEuclidean": float(np.linalg.norm(np.subtract(middle["meanChromaticity"], other["meanChromaticity"]))) if middle["meanChromaticity"] is not None and other["meanChromaticity"] is not None else None,
            }
        result["betweenDistances"] = distances
    return result


def _crossings(points, candidates, side_name):
    """Retain disjoint crossings of one chain as distinct transition ranges."""
    axis = METHOD["scanAxes"][side_name]
    along, scan = (0, 1) if axis == "x" else (1, 0)
    bins = {}
    for candidate in candidates:
        if candidate["side"] != side_name:
            continue
        start, stop = candidate["sourcePointStart"], candidate["sourcePointStopExclusive"]
        if not (0 <= start < stop <= len(points)):
            raise ValueError("invalid candidate source range")
        p = np.unique(points[start:stop], axis=0)
        p = p[np.lexsort((p[:, along], p[:, scan]))]
        breaks = np.r_[0, np.flatnonzero((np.diff(p[:, scan]) != 0) | (np.diff(p[:, along]) != 1)) + 1, len(p)]
        for lo, hi in zip(breaks[:-1], breaks[1:]):
            scan_index = int(p[lo, scan])
            bins.setdefault(scan_index, []).append({
                "candidateId": candidate["candidateId"],
                "range": [int(p[lo, along]), int(p[hi - 1, along])],
            })
    for crossings in bins.values():
        crossings.sort(key=lambda item: (item["range"], item["candidateId"]))
    return axis, bins


def competing_pairs(crossings):
    """Retain overlapping alternatives, then every adjacent-component pairing.

    Sorting endpoints alone is insufficient when one transition encloses another.
    Components use inclusive occupied intervals; touching pixel ranges remain
    separate so the zero-between-pixel state is retained.
    """
    components = []
    end = -1
    for item in crossings:
        if not components or item["range"][0] > end:
            components.append([])
            end = item["range"][1]
        else:
            end = max(end, item["range"][1])
        components[-1].append(item)
    for component in components:
        for a, b in combinations(component, 2):
            if b["range"][0] <= a["range"][1]:
                yield a, b
    for first, second in zip(components, components[1:]):
        yield from product(first, second)


def assess_surroundings(rgb, points, candidates):
    """Visit every native scan; retain missing, singleton and competing cases."""
    if not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("native RGB8 required")
    points = np.asarray(points)
    if points.ndim != 2 or points.shape[1] != 2 or points.dtype.kind not in "iu":
        raise ValueError("integer native edge points required")
    height, width = rgb.shape[:2]
    if len(points) and ((points < 0).any() or (points[:, 0] >= width).any() or (points[:, 1] >= height).any()):
        raise ValueError("edge point outside source raster")
    if len({c["candidateId"] for c in candidates}) != len(candidates):
        raise ValueError("duplicate candidate identity")
    if any(c["side"] not in METHOD["scanAxes"] for c in candidates):
        raise ValueError("unknown candidate side")
    sides = {}
    totals = {"scans": 0, "pairs": 0, "eligiblePairs": 0,
              "complete": 0, "clipped_support": 0,
              "intervening_transition": 0, "overlapping_transitions": 0,
              "no_between_pixels": 0, "no_transition": 0, "single_transition": 0,
              "competing": 0}
    for side in METHOD["scanAxes"]:
        axis, bins = _crossings(points, candidates, side)
        scans = []
        side_summary = dict.fromkeys(totals, 0)
        for index in range(height if axis == "x" else width):
            crossings = bins.get(index, [])
            pairs = []
            for a, b in competing_pairs(crossings):
                pair = compare_pair(rgb, axis, index, a, b)
                pair["otherTransitionsInBands"] = {
                    name: [c for c in crossings if c is not a and c is not b
                           and c["range"][1] >= band["availableRange"][0]
                           and c["range"][0] < band["availableRange"][1]]
                    for name, band in pair["bands"].items()
                }
                if pair["otherTransitionsInBands"].get("between"):
                    pair.pop("betweenDistances", None)
                    if pair["status"] == "complete":
                        pair["status"] = "intervening_transition"
                pair["comparisonEligible"] = pair["status"] == "complete" and not any(pair["otherTransitionsInBands"].values())
                pairs.append(pair)
            scan_status = "competing" if len(crossings) > 1 else "single_transition" if crossings else "no_transition"
            scans.append({"scanIndex": index, "status": scan_status,
                          "transitions": crossings, "pairs": pairs})
            side_summary["scans"] += 1
            side_summary[scan_status] += 1
            side_summary["pairs"] += len(pairs)
            for pair in pairs:
                side_summary[pair["status"]] += 1
                side_summary["eligiblePairs"] += int(pair["comparisonEligible"])
        for key, value in side_summary.items():
            totals[key] += value
        sides[side] = {"axis": axis, "scans": scans, "summary": side_summary}
    return {"schemaVersion": 1, "type": "id_cadastral_perimeter_surroundings",
            "method": METHOD, "sourceDimensions": [width, height], "sides": sides,
            "summary": totals, "physicalPerimeterStatus": "unresolved"}
