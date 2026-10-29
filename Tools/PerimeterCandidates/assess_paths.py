"""Attach appearance-continuation hypotheses to exact assembled path locations."""
from collections import defaultdict
import numpy as np


def _feature(stats, name):
    if name == "chromaticity":
        value = stats.get("meanChromaticity")
        return None if value is None else np.asarray(value, float)
    intensity = stats.get("meanChannelIntensity", 0)
    variation = stats.get("meanAbsoluteAdjacentRGBDifference")
    if intensity <= 0 or variation is None:
        return None
    return np.asarray(variation, float) / intensity


def appearance_hypothesis(pair, inward_sign):
    """Compare two continuation hypotheses, without a material-class assertion.

    Non-conflicting feature preferences support one hypothesis. Equal distances
    are neutral; unavailable channels and contaminated supports do not vote.
    """
    if inward_sign not in (-1, 1):
        raise ValueError("inward scan orientation must be nonzero")
    interior, exterior = ("after", "before") if inward_sign > 0 else ("before", "after")
    inward_transition = "second" if inward_sign > 0 else "first"
    outward_transition = "first" if inward_sign > 0 else "second"
    result = {"status": "insufficient", "supportedTransition": None,
              "inwardTransition": inward_transition, "outwardTransition": outward_transition,
              "bandRoles": {"interior": interior, "between": "between", "exterior": exterior},
              "features": {}, "reason": pair["status"]}
    available_stats = {role: pair.get("bands", {}).get(name, {}).get("statistics", {}) for role, name in result["bandRoles"].items()}
    if all("meanChannelIntensity" in s for s in available_stats.values()):
        intensity = {role: float(s["meanChannelIntensity"]) for role, s in available_stats.items()}
        result["intensity"] = intensity
        result["betweenDarkerThanBoth"] = intensity["between"] < min(intensity["interior"], intensity["exterior"])
    if not pair.get("comparisonEligible"):
        result["reason"] = "incomplete_or_contaminated_support"
        return result
    stats = {role: pair["bands"][name]["statistics"] for role, name in result["bandRoles"].items()}
    votes = []
    for name in ("chromaticity", "relativeDirectionalVariation"):
        f = {role: _feature(s, name) for role, s in stats.items()}
        if any(v is None for v in f.values()):
            result["features"][name] = {"preference": "undefined"}
            continue
        inside = float(np.linalg.norm(f["between"] - f["interior"]))
        outside = float(np.linalg.norm(f["between"] - f["exterior"]))
        preference = "exterior" if outside < inside else "interior" if inside < outside else "equal"
        result["features"][name] = {"interiorDistance": inside, "exteriorDistance": outside,
                                    "preference": preference, "interiorMinusExteriorDistance": inside - outside}
        if preference != "equal":
            votes.append(preference)
    intensity = {role: float(s["meanChannelIntensity"]) for role, s in stats.items()}
    result["intensity"] = intensity
    result["betweenDarkerThanBoth"] = intensity["between"] < min(intensity["interior"], intensity["exterior"])
    if len(set(votes)) > 1:
        result.update(status="conflicting", reason="appearance_features_disagree")
    elif votes:
        role = votes[0]
        result.update(status="supports_inward_transition" if role == "exterior" else "supports_outward_transition", reason=role + "_appearance_continuation",
                      supportedTransition=inward_transition if role == "exterior" else outward_transition)
    else:
        result["reason"] = "no_discriminating_appearance_feature"
    return result


def _membership(points, candidates, assembly):
    source_paths = defaultdict(set)
    for path in assembly["paths"]:
        vertices = {tuple(p) for p in path["points"]}
        for index in path["sourceSegmentStartIndices"]:
            if not 0 <= index < len(points) - 1:
                raise ValueError("path segment outside source points")
            for endpoint in (index, index + 1):
                if tuple(points[endpoint]) in vertices:
                    source_paths[endpoint].add(path["pathId"])
    lookup = defaultdict(lambda: defaultdict(set))
    coverage = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for candidate in candidates:
        axis = 1 if candidate["side"] in ("top", "bottom") else 0
        for index in range(candidate["sourcePointStart"], candidate["sourcePointStopExclusive"]):
            x, y = map(int, points[index])
            scan, position = (x, y) if axis == 1 else (y, x)
            paths = source_paths.get(index, set())
            lookup[(candidate["candidateId"], scan)][position].update(paths)
            for path in paths:
                coverage[path][candidate["side"]][scan].add(position)
    return lookup, coverage


def _attach(lookup, transition, scan):
    matches = defaultdict(list)
    membership = lookup.get((transition["candidateId"], scan), {})
    lo, hi = transition["range"]
    for position in range(lo, hi + 1):
        for path in membership.get(position, ()):
            matches[path].append(position)
    return [{"pathId": path, "sourcePositions": positions} for path, positions in sorted(matches.items())]


def assess_paths(points, candidates, assembly, evidence, prior=None):
    """Return exact comparison links, hypotheses, per-path spatial coverage."""
    points = np.asarray(points)
    if isinstance(candidates, dict):
        prior = candidates["prior"]
        candidates = candidates["candidates"]
    if prior is None:
        raise ValueError("candidate prior is required for inward orientation")
    lookup, coverage = _membership(points, candidates, assembly)
    side_names = prior["sideNames"]
    normals = np.asarray(prior["inwardNormals"], float)
    observations = []
    path_votes = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    path_refs = defaultdict(list)
    for side, data in evidence["sides"].items():
        component = 0 if data["axis"] == "x" else 1
        normal = normals[side_names.index(side), component]
        if normal == 0:
            raise ValueError("scan axis cannot orient this side")
        for scan in data["scans"]:
            index = scan["scanIndex"]
            for pair_index, pair in enumerate(scan["pairs"]):
                links = {role: _attach(lookup, pair[role], index) for role in ("first", "second")}
                if not any(links.values()):
                    continue
                hypothesis = appearance_hypothesis(pair, 1 if normal > 0 else -1)
                attribution = {role: len(matches) == 1 and len(matches[0]["sourcePositions"]) == pair[role]["range"][1] - pair[role]["range"][0] + 1
                               for role, matches in links.items()}
                if not all(attribution.values()):
                    hypothesis["appearanceOnlyStatus"] = hypothesis["status"]
                    hypothesis.update(status="insufficient", reason="ambiguous_or_missing_path_attribution", supportedTransition=None)
                record_id = len(observations)
                observations.append({"comparisonId": record_id, "side": side, "axis": data["axis"],
                                     "scanIndex": index, "pairIndex": pair_index,
                                     "transitions": {role: pair[role] for role in links},
                                     "pathLinks": links, "pathAttributionComplete": attribution, "hypothesis": hypothesis,
                                     "bands": pair["bands"], "comparisonEligible": pair.get("comparisonEligible", False)})
                linked_both = {p["pathId"] for p in links["first"]} & {p["pathId"] for p in links["second"]}
                for role, paths in links.items():
                    for link in paths:
                        path_id = link["pathId"]
                        status = hypothesis["status"]
                        supported = status in ("supports_inward_transition", "supports_outward_transition")
                        if path_id in linked_both and supported:
                            vote = "conflicting"
                        elif supported:
                            vote = "support" if hypothesis["supportedTransition"] == role else "opposition"
                        else:
                            vote = status
                        for position in link["sourcePositions"]:
                            path_votes[path_id][side][(index, position)].add(vote)
                        path_refs[path_id].append({"comparisonId": record_id, "transition": role,
                                                   "sourcePositions": link["sourcePositions"], "outcome": vote})
    results = []
    for path in assembly["paths"]:
        path_id = path["pathId"]
        sides = {}
        for side, locations in coverage[path_id].items():
            kinds = ("support", "opposition", "conflicting", "insufficient", "uncompared", "mixed")
            counts = dict.fromkeys(kinds, 0)
            pixel_counts = dict.fromkeys(kinds, 0)
            scan_outcomes = []
            for index in sorted(locations):
                position_outcomes = []
                for position in sorted(locations[index]):
                    votes = path_votes[path_id][side].get((index, position), set())
                    if "conflicting" in votes or {"support", "opposition"} <= votes:
                        outcome = "conflicting"
                    elif len(votes) > 1:
                        outcome = "mixed"
                    elif votes:
                        outcome = next(iter(votes))
                    else:
                        outcome = "uncompared"
                    pixel_counts[outcome] += 1
                    position_outcomes.append({"sourcePosition": position, "outcome": outcome})
                outcomes = {item["outcome"] for item in position_outcomes}
                outcome = next(iter(outcomes)) if len(outcomes) == 1 else "mixed"
                counts[outcome] += 1
                scan_outcomes.append({"scanIndex": index, "outcome": outcome, "positions": position_outcomes})
            counts["observedScans"] = len(locations)
            counts["observedPixels"] = sum(pixel_counts.values())
            counts["signedSupportScans"] = counts["support"] - counts["opposition"]
            counts["signedSupportFraction"] = counts["signedSupportScans"] / len(locations) if locations else 0
            assessment = "conflicting" if counts["conflicting"] or (counts["support"] and counts["opposition"]) else "mixed" if counts["mixed"] else "support" if counts["support"] else "opposition" if counts["opposition"] else "insufficient"
            sides[side] = {"coverage": counts, "pixelCoverage": pixel_counts, "scans": scan_outcomes, "assessment": assessment}
        all_counts = {kind: sum(s["pixelCoverage"][kind] for s in sides.values()) for kind in ("support", "opposition", "conflicting", "mixed")}
        classification = "mixed" if all_counts["conflicting"] or all_counts["mixed"] or (all_counts["support"] and all_counts["opposition"]) else "support_only" if all_counts["support"] else "opposition_only" if all_counts["opposition"] else "insufficient"
        results.append({"pathId": path_id, "sides": sides, "comparisons": path_refs[path_id], "classification": classification})
    rankings = {side: [p["pathId"] for p in sorted((p for p in results if side in p["sides"]),
                  key=lambda p: (-p["sides"][side]["coverage"]["signedSupportScans"], p["pathId"]))] for side in side_names}
    outcomes = defaultdict(int)
    for record in observations:
        outcomes[record["hypothesis"]["status"]] += 1
    classifications = defaultdict(int)
    for path in results:
        classifications[path["classification"]] += 1
    return {"schemaVersion": 1, "type": "id_cadastral_path_appearance_assessment", "paths": results,
            "comparisons": observations, "rankedPathIdsBySide": rankings,
            "summary": {"comparisons": len(observations), "hypothesisOutcomes": dict(outcomes), "pathClassifications": dict(classifications)},
            "method": {"name": "appearance_continuation_hypotheses", "version": 1,
                       "ranking": "descending_signed_unique_support_scans", "rankingUnit": "native_scan",
                       "physicalSelection": "unresolved", "darknessVotes": False,
                       "featureAgreement": "at_least_one_strict_preference_and_no_opposite_preference"}}
