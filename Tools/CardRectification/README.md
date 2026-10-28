# Boundary-derived rectification

This host experiment estimates a card plane from the observed native perimeter.
It preserves the perimeter independently, including damage and interior rings.
It does not change production Swift rectification.

## Method and source decisions

Every exterior unit pixel-edge midpoint is expanded from the GDAL polygon; no
turn-vertex weighting, decimation, random subset or reduced raster is used.
Saved corners label sides and select support, but do not prescribe fitted lines.
Points with side projection between 10% and 90% support straight-edge fitting;
rounded-corner regions remain in full residual diagnostics. This is a geometric
support assumption, not a speed optimization. Runs at5% and15% exclusion measure
sensitivity without selecting whichever looks best.

SVD initializes each line using all eligible positions. SciPy1.13.1
least_squares(method='trf',loss='soft_l1') evaluates all residuals at every step.
The scale is max(0.5 native pixels,1.4826×MAD of initial residuals). Half a pixel
is an explicit raster quantization floor. Soft loss reduces influence without
removing local departures. Fitted lines define plane corners; no fitted line
replaces the observed contour.

OpenCV4.12 robust fitLine was rejected here because its implementation initializes
from random subsets of10points. This would conflict with the owner's no-sampling
requirement. SciPy supplies the nonlinear solver and NumPy the SVD/linear solve;
no optimizer, homography solver or interpolator is handwritten.

## Coordinates and preservation

Source coordinates refer to pixel edges. H_edge maps to output pixel edges;
OpenCV samples integer centers, so H_cv=T(-0.5)×H_edge×T(+0.5).
The nominal card plane is85.60×53.98mm with x right,y down. Output sampling stays
50pixels/mm for comparison with saved rectification. This is derivative sampling,
not an independent physical dimension measurement.

The output extent covers the nominal rectangle and every transformed contour
vertex, with2pixels interpolation margin. originCardMillimeters records padding.
Warp directly from the retained full-resolution upright RGB source once using
OpenCV bilinear interpolation. Never re-warp the saved rectified PNG. Transform
all observed polygon rings independently; do not snap dents onto the rectangle.

The package includes manifest.json, rectified.png, contour.json and residuals.npz.
Residual arrays record sourcePositions, edgeIndex, fitSupport,
signedResidualSourcePixels and robustInfluence for every exterior unit edge.
Source and boundary hashes are checked before and after processing. Publication
uses the existing no-overwrite durable publisher. Failures publish no package.

## Run

```sh
Artifacts/gis-baseline-20260911/geotiff-env/bin/python Tools/CardRectification/test_rectify.py
Artifacts/gis-baseline-20260911/geotiff-env/bin/python Tools/CardRectification/rectify.py Artifacts/gis-baseline-20260911 Artifacts/gis-baseline-20260911/boundary-production-v1 Artifacts/gis-baseline-20260911/rectification-v1
```

Choose a new output directory for each run. Start PixelViewer with
`--rectification <package>` alongside its required baseline/boundary arguments.
The right pane's selector switches saved and boundary-derived images and their
coordinate transforms together. The orange overlay is separate from image pixels.

## Provenance

Inspected2026-09-11, no source copied:
- https://docs.scipy.org/doc/scipy-1.13.1/reference/generated/scipy.optimize.least_squares.html
- https://github.com/scipy/scipy/blob/v1.13.1/scipy/optimize/_lsq/least_squares.py
- https://github.com/scipy/scipy/blob/v1.13.1/LICENSE.txt (BSD-3-Clause)
- https://raw.githubusercontent.com/opencv/opencv/4.12.0/modules/imgproc/src/linefit.cpp
- https://docs.opencv.org/4.12.0/da/d54/group__imgproc__transform.html
- https://raw.githubusercontent.com/opencv/opencv/4.12.0/modules/imgproc/src/imgwarp.cpp

Dependencies already pinned under Tools/CardBoundary; no new binary dependency.
OpenCV Apache-2.0 and inherited notices remain as recorded there. Removal seam:
remove this host tool and optional viewer comparison routes. No Swift API changed.

Low residuals do not establish that an edge is physical rather than shadow.
This projective plane does not correct lens distortion or nonplanarity. The saved
rectified raster also has a different historical decode path, so image appearance
differences between saved and new images are not exclusively geometric.
