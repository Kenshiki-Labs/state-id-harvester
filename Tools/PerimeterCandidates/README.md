# Perimeter candidates

Automatic, prior-localized inventory and surrounding-image evidence. No physical
perimeter is selected. Candidate IDs are generated from source runs, never supplied
as answers. The source raster and retained EdgeDrawing dataset are explicit inputs.

## Run

```
python Tools/PerimeterCandidates/run.py BASELINE EDGES NEW_OUTPUT
python -m unittest discover -s Tools/PerimeterCandidates -p 'test_*.py'
```

Use the existing CardBoundary/GeoTIFF environment. Add `--perimeter NEW_OUTPUT`
to PixelViewer along with its matching `--edges` input. The viewer exposes native
candidate coordinates, relationships, provenance and the full evidence download.

`config.json` records the localization hypothesis: corridor width is 4% of the
shortest captured quadrilateral side, inherited from the existing boundary search.
This is an explicit tunable search extent, not a measured card property or a
validated coverage guarantee. A bad captured quadrilateral can exclude the real
perimeter. All upstream points retain four-side membership and exclusion counts;
there is no maximum candidate count or native-point reduction.

Each finite side corridor retains every contiguous original chain run, including
singletons. Runs are never joined, smoothed, or fitted. Point-center coordinates
are index plus one half. Cross-side relationships distinguish shared source points
from different portions of the same chain; neither proves a perimeter connection.
The original source chain remains available through its bound edge dataset.

Surrounding evidence visits every native image row/column on each corresponding
side, including missing and competing cases. Neighborhood depth follows candidate
separation. See [EVIDENCE.md](EVIDENCE.md) for full definitions and overlap handling.
Recorded pixel intervals permit inspection of every contributing source sample.
These are axis-directed profiles, not perpendicular physical thicknesses.

The current output is candidate discovery plus descriptive assessment. It has no
calibrated physical-edge classifier, global closed-perimeter optimizer, or accepted
replacement mask. Unsupported selection remains unresolved. Existing rectification
and card measurements are not changed.

## Sources and implementation

Existing pinned NumPy 2.0.2 supplies projection, norms, clipping, sorting, differences
and reductions. Source documentation inspected:

- https://numpy.org/doc/2.0/reference/generated/numpy.diff.html
- https://numpy.org/doc/2.0/reference/generated/numpy.einsum.html
- https://numpy.org/doc/2.0/reference/generated/numpy.mean.html

No upstream code is copied; NumPy uses BSD-3-Clause and no dependency is added.
The local implementation assembles native source ranges, spatial relationships,
and provenance because numerical primitives do not provide this dataset contract.
Existing `CardEdges` admission and `CardBoundary` atomic publication are reused.
Remove this directory and the optional PixelViewer perimeter input to remove the
experiment. It is not integrated into Swift capture behavior.

## Verification boundary

Tests cover native run preservation, translated inputs, multiple alternatives,
independent GEOS finite-side membership, malformed partitions, complete scans,
clipping, overlap, contamination, and package byte/lineage admission. Hash admission
is not a full semantic re-execution of evidence. No production-grade or physical
accuracy claim follows from those tests.

## Assemble observed paths

```
python Tools/PerimeterCandidates/assemble.py EDGES CANDIDATES NEW_ASSEMBLY
```

Add `--assembly NEW_ASSEMBLY` alongside `--perimeter CANDIDATES` in PixelViewer.
The assembly view shows one path at a time, ordered by observed length, with open
ends and clickable branch continuations. Length order is not confidence ranking.

Assembly unions overlapping source ranges, reuses `CardTopology.audit` for exact
noding, then delegates degree-two joins to `shapely.line_merge`. At a branch the
incident paths collectively retain all possible continuations; no exponential
list of walks or preferred turn is fabricated. A geometric crossing is a graph
junction, not proof of a material connection. Isolated observations are retained.
No proximity snapping, segment insertion, gap pairing or shape fitting occurs.
An open endpoint may be a detector break, a localization cut or a real feature end;
its cause remains unclassified. Closed paths, if present, are not authentication.

Sources inspected before implementation:
- https://shapely.readthedocs.io/en/2.0.7/reference/shapely.line_merge.html
- https://shapely.readthedocs.io/en/2.0.7/reference/shapely.node.html

Existing Shapely 2.0.7 / GEOS and SciPy dependencies and notices are retained under
CardTopology; none added. The local adapter supplies source-range admission,
provenance and graph presentation. Output retains original source-segment indices,
candidate identities, connected components and node incidence. A GEOS symmetric
difference check requires unchanged linework before publication. Tests exercise
joins, dents, branches, open gaps, cycles, diagonal crossings, isolated points and
rejected altered source geometry. The original candidate package stays immutable.
