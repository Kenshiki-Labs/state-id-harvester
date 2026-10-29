# Native edge candidates

This host experiment maps connected image transitions in the unchanged full-scene
RGB decode. It does not classify a chain as the physical card perimeter. It uses
OpenCV contrib EdgeDrawing 4.12.0 via `detectEdges` and `getSegments`. No upstream
algorithm source is copied or modified. The wrapper, binary dataset, admission
checks and viewer seam are local code.

## Reproduce

Use a separate virtual environment; do not install competing OpenCV packages in
the existing baseline environment:

```
python3 -m venv Artifacts/gis-baseline-20260911/edge-env
Artifacts/gis-baseline-20260911/edge-env/bin/pip install -r Tools/CardEdges/requirements-macos-py39.txt
Artifacts/gis-baseline-20260911/edge-env/bin/python Tools/CardEdges/detect.py Artifacts/gis-baseline-20260911 Artifacts/gis-baseline-20260911/edge-candidates-v1
Artifacts/gis-baseline-20260911/edge-env/bin/python -m unittest discover -s Tools/CardEdges -p test_edges.py -v
```

Run detector and evaluation-helper tests together in the isolated edge environment:

```
Artifacts/gis-baseline-20260911/edge-env/bin/python -m unittest discover -s Tools/CardEdges -p 'test_*.py' -v
```

The retained-image evaluation also validates the existing GrabCut boundary with
Rasterio and Shapely. Run that CLI in the existing GeoTIFF environment, which
contains those dependencies. Evaluation does not import or execute the detector:

```
Artifacts/gis-baseline-20260911/geotiff-env/bin/python Tools/CardEdges/evaluate.py --baseline Artifacts/gis-baseline-20260911 --edges Artifacts/gis-baseline-20260911/edge-candidates-v1 --boundary Artifacts/gis-baseline-20260911/boundary-production-v1 --out Artifacts/gis-baseline-20260911/edge-review-v2
Artifacts/gis-baseline-20260911/geotiff-env/bin/python -m unittest discover -s Tools/CardEdges -p test_evaluate.py -v
```

Use a new output directory on every review; `edge-review-v1` is the retained first
execution. Its `report.html` displays six source/edge/GrabCut comparison sets,
`review.json` records coverage and source identities, and `profiles.npz` retains
every diagnostic row/column count. The separate visual interpretation is retained
at `Artifacts/gis-baseline-20260911/edge-visual-review-v1/REPORT.md`, with JSON and
the exact measurement script alongside it. Coverage counts are image-transition
availability measurements, never physical-boundary accuracy scores.

Existing output is never overwritten. Dataset admission returns immutable arrays
and byte snapshots; viewer routes consume snapshots. Points are integer source
pixel indices; add `(0.5, 0.5)` to locate their centers in source edge coordinates.
NPY files are little-endian, C-order version 1. Every returned nonempty chain is
retained, without simplification, line fitting or a post-detection length filter.
A chain's length is the sum of distances between consecutive retained points.

## Source and parameter audit

Pinned source:
https://github.com/opencv/opencv_contrib/blob/4.12.0/modules/ximgproc/src/edge_drawing.cpp

Pinned license:
https://github.com/opencv/opencv_contrib/blob/4.12.0/LICENSE

`THIRD_PARTY_LICENSE.txt` preserves that Apache 2.0 license. The binary wheel also
ships its third-party notices; no binary or wheel is redistributed by this tool.

`config.json` is the versioned parameter source. This first experiment uses the
upstream default intensity-gradient threshold 20, anchor threshold 0, Prewitt
operator, sum-gradient magnitude and Gaussian sigma 1 (native 5x5 prefilter).
These are declared hypotheses, not camera-independent calibrated thresholds.
RGB is converted with OpenCV `COLOR_RGB2GRAY` to isolate intensity transitions.
Equal-luminance chromatic edges can therefore be missed; the original RGB remains
unchanged. This is a limitation of the experiment, not an assertion that chroma
is irrelevant.

`ScanInterval=1` visits every eligible anchor pixel. Upstream excludes a two-pixel
frame from anchor testing and a one-pixel frame from gradient calculation; that
stencil support exclusion is recorded. No resizing, image pyramid, crop, mask or
reduced anchor grid is used. Gaussian smoothing is a declared native-resolution
derivative, not a replacement source raster. `MinPathLength=3` is the smallest
value upstream permits. Upstream can still emit shorter final segments; those
are retained. PFmode is off, avoiding its additional statistical validation path.
Line-specific settings are explicit but inactive because `detectLines` is never
called. Threads are fixed to one for repeatability, not runtime optimization.

## Dependency scope and removal

The pinned macOS arm64 contrib headless wheel downloads 46.9 MB. Runtime depends
on NumPy (pinned 2.0.2); Pillow 11.3.0 serves existing native source admission.
There are no downloaded models, training datasets or network processing calls.
OpenCV is an established maintained project; this frozen release is evaluated
rather than automatically upgraded. Remove `Tools/CardEdges` and the optional
viewer dataset input to remove the dependency; Swift products are unaffected.

## Evidence limits

A candidate chain is an image observation. Physical perimeter selection remains
unresolved until compared with visible material transitions. Synthetic tests
verify adjacent transitions, repeatability, source preservation and package
integrity. Evaluation reports retain actual local crops and chain coordinates;
an unregistered screenshot of damage is not converted into fabricated coordinates.
