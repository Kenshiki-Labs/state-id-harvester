# Complete perimeter measurements

Every original and rectified row and column is intersected with the retained
polygon, including its holes, at pixel centers AND pixel edges. No scan positions
are skipped. Source unit perimeter vertices and their mapped coordinates/radial
distances are retained. Intersections are continuous geometry; raster samples
and pixel-edge coordinates are distinguished. Fractional endpoints are not rounded.

The accepted input here is the existing GrabCut observation, whose physical-edge
selection remains unresolved. Millimeter mappings use the retained rectification;
no new fit, warp or smoothing occurs in the measurement step. Known ID-1 dimensions
are 85.60 x 53.98 mm. Registration accuracy remains distinct from that known frame.

Run in the existing geotiff-env:

```
python Tools/CardMeasurements/measure.py BASELINE BOUNDARY RECTIFICATION NEW_MEASUREMENTS
python Tools/CardMeasurements/models.py NEW_MEASUREMENTS RECTIFICATION NEW_MODELS
python -m unittest discover -s Tools/CardMeasurements -p 'test_*.py'
```

Use Artifacts/gis-baseline-20260911/geotiff-env/bin/python for those commands.
Existing output directories are refused. The models CLI requires the complete
validated measurement package to exist before fitting. Both packages stay local.
The viewer accepts --measurements PACKAGE --measurement-models MODEL_PACKAGE,
with their matching --rectification. It can inspect any rectified row/column at
centers or edges, show all intervals, both diagonals, extended registered side
lines and conditional corner radius arcs. Defaults remain clear.

## Storage

Each frame and axis has scans.npy, offsets.npy and intervals.npy. The manifest
names every column. Offsets preserve every component of the polygon/scanline
intersection. Outer span and occupied length are distinct when there are holes
or multiple intervals. Empty, single, multiple, tangent and boundary-overlap
states are explicit; an empty measurement is not a zero-size card. Every record
inherits physicalPerimeterStatus=unresolved independently of geometric status.

perimeter.npy retains every unit native perimeter vertex, including holes, with
source/rectified/card coordinates, center distance and ring ID. diagonals.json
records both center-crossing diagonal lines, all intersections and signed-side
center-to-first-perimeter distances. Rounded corners shorten physical diagonal
intersections relative to the virtual sharp-corner rectangle diagonal.

## Models and checks

The four extended side lines and their virtual intersections come from the
retained registration model. They do not redefine physical rounded corners.
The 3-4-5 check measures endpoints 3 and 4 mm along adjacent registered sides;
it detects angular inconsistency but is not independent physical-edge evidence.
A homography constructed to make a rectangle should satisfy this check by design.

Corner-radius estimates use all exterior unit vertices, partitioned by nearest
known-frame corner, fitting a circular arc tangent to registered side lines.
SciPy least_squares soft_l1 uses a 0.02 mm residual scale (one existing rectified
pixel), initial radius 3 mm, bounds [0,26.99] mm. This starting point is not a
claimed card radius. Complete straight and curved support participates in the
rounded-corner signed-distance model; no points are thinned or removed. Each
estimate reports RMS and maximum absolute residual. These are conditional model
estimates, especially sensitive to the known bottom/left boundary errors.

## Reuse and verification

Shapely 2.0.7 / GEOS intersection(grid_size=0) computes double-precision polygon
intersections without snapping. NumPy retains arrays. SciPy 1.13.1 provides the
separate optimizer. Existing atomic publication and baseline admission are reused.
No dependency added or upstream implementation copied. Existing BSD-3-Clause,
GEOS LGPL-2.1 and SciPy bundled notices are retained in CardTopology/licenses.
Removal seam is this host tool and optional viewer measurement input.

Sources inspected (installed wrappers plus primary documentation):
- https://shapely.readthedocs.io/en/2.0.7/reference/shapely.intersection.html
- https://github.com/shapely/shapely/blob/2.0.7/shapely/set_operations.py
- https://docs.scipy.org/doc/scipy-1.13.1/reference/generated/scipy.optimize.least_squares.html

Baseline: measurements-v1 contains 38,160 scan positions over source 5160x6880
and rectified 4316x2722. Independent source interval raster reconstruction agrees
with all 35,500,800 mask pixels in EACH axis. measurement-models-v1 is separate;
measurements-executed-source-v1 preserves executed sources before validation
hardening. This verifies the retained mask, not physical-boundary correctness.
