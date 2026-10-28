# ID Cadastral

Run the complete retained workspace from the repository root on this Mac:

```sh
CAPTURE_BASE=Artifacts/gis-baseline-20260911
"$CAPTURE_BASE/geotiff-env/bin/python" Tools/PixelViewer/serve.py \
  --baseline "$CAPTURE_BASE" \
  --boundary "$CAPTURE_BASE/boundary-production-v1" \
  --rectification "$CAPTURE_BASE/rectification-v1" \
  --edges "$CAPTURE_BASE/edge-candidates-v1" \
  --topology "$CAPTURE_BASE/topology-v2" \
  --measurements "$CAPTURE_BASE/measurements-v1" \
  --measurement-models "$CAPTURE_BASE/measurement-models-v1" \
  --perimeter "$CAPTURE_BASE/perimeter-candidates-v2" \
  --assembly "$CAPTURE_BASE/perimeter-assembly-v1" \
  --path-assessment "$CAPTURE_BASE/path-assessment-v2" \
  --working-area "$CAPTURE_BASE/interior-working-v1" \
  --port 8767
```

Open `http://127.0.0.1:8767` after startup. If that port already hosts the
retained workspace, use it or choose a separate port for an audit. The explicit
package arguments preserve pink/blue edges, topology, diagonals, side lines,
radii, measurements and working-area overlays. A boundary-only launch is a
partial workspace, not the consolidated baseline. Missing packages fail admission;
do not silently remove arguments to make the launch succeed.

The example input is `Artifacts/gis-baseline-20260911/front-*`. The server checks
original and rectified SHA-256 against the retained geometry before starting.
ImageMagick creates a separate full-frame, upright sRGB 8-bit PNG for browser
viewing. It verifies dimensions against the transform and records the decoder,
operation and output hash in `browser-viewer/manifest.json`. HEIC is untouched.
This display derivative does not replace the host TIFF analysis contract.

Only explicit allowlisted routes are served, on loopback, with no cache or directory
listing. No external scripts, uploads, analytics or runtime network dependency.
All image artifacts stay under the existing ignored Artifacts directory.

Hover links pixel centers through the retained projective matrices. Click pins
a point; Escape resumes hover. Each pane has Fit, 1:1 and Pixel zoom controls.
Pixel zoom centers the selected point. Wheel zoom anchors under the mouse;
drag pans. Focus a canvas for arrow-key pan and +/- zoom. Percentages express
CSS pixels per image pixel. Nearest-neighbor display applies at 100% and above.
RGB samples come from a full-size, unoverlaid sRGB canvas, not the zoomed view.
A mapped coordinate samples its containing pixel; the coordinate retains its
fractional position. Rectified RGB need not equal source RGB because of decode
and resampling differences. Out-of-image locations have no RGB or mm sample.

## Scope and sources

This is owner-requested host inspection UI, not SDK analysis or authentication.
The source and geometry convention are Decision 0039. Millimeters are nominal.
No lens calibration, anomaly detection, classification or new capture is added.

Sources inspected 2026-09-11:
- https://developer.mozilla.org/en-US/docs/Web/API/CanvasRenderingContext2D/getImageData
- https://developer.mozilla.org/en-US/docs/Web/API/CanvasRenderingContext2D/imageSmoothingEnabled
- https://developer.apple.com/documentation/webkitjs/canvasrenderingcontext2d/1777972-imagesmoothingenabled
- https://openseadragon.github.io/examples/tilesource-image/
- https://openseadragon.github.io/examples/ui-zoom-and-pan/
- Existing ImageMagick provenance: References/sources/heic-tiff-derivation.md

Implementation exception: native Canvas is sufficient for this fixed two-image
inspection UI and exposes exact full-resolution pixel sampling independently
of display zoom. OpenSeadragon is suitable for a future tile viewer, but adds a
third-party runtime and tile-coordinate plumbing unnecessary for this bounded
baseline. No third-party implementation code was copied. Projection only applies
the existing matrices; no homography solver or resampler is implemented here.
This version loads full images (roughly 188 MB for two RGBA rasters alone, plus
browser copies); it is a desktop baseline, not a phone-memory benchmark.

## Baseline verification (2026-09-11)

- Original/output hashes verified before serving; upright decode is 5160 × 6880.
- All four retained source corners project within 0.000003 mm of nominal
  rectangle corners (numerical consistency only). Matrix round trips pass.
- Real Chromium inspection exercised linked selection, pinning, pixel zoom,
  wheel zoom, drag and Fit; final interaction run had no page exceptions.
- Rectified pixel [2140,1350] sampled RGB [44,48,47], mapped to original
  coordinate (2592.076,3449.926), containing pixel [2592,3449], RGB [22,24,23].
  Both samples independently match decoded PNG pixels via Pillow.
- Browser color management may round other decoded colors; this is a display
  inspector, not a raw sensor or color-calibration measurement tool.
- Screenshots retained locally in ignored output/playwright/.

## GeoTIFF and JSON display

ID Cadastral now shows the GeoTIFF in the right pane, alongside the original
image decode. Startup validates the TIFF hash and its baseline lineage, then
Pillow creates a lossless full-resolution browser PNG from the TIFF. Every
RGBA value is checked after decoding; the PNG is a display representation,
not a substitute evidence file. This host step uses existing Pillow and NumPy.

The page exposes dataset details, the full provenance JSON, and direct GeoTIFF
and JSON downloads. The raster retains linked cursors and RGB/hex inspection.
Readouts show both nominal card y-down and GIS y-up coordinates. The browser
checks that the displayed TIFF lineage matches the manifest. No PNG fallback
is used when the TIFF is missing or its hash is wrong.

## Scene object layer

Start with the isolated environment now that object generation uses GEOS/GDAL:

```sh
Artifacts/gis-baseline-20260911/geotiff-env/bin/pip install --only-binary=:all: -r Tools/PixelViewer/requirements-macos-py39.txt
Artifacts/gis-baseline-20260911/geotiff-env/bin/python Tools/PixelViewer/serve.py --baseline Artifacts/gis-baseline-20260911 --boundary Artifacts/gis-baseline-20260911/boundary-v1
```

`objects.py` reuses Shapely 2.0.7 (BSD-3-Clause, GEOS LGPL-2.1; installed wheel
retains its notices) for the saved quadrilateral and image-extent difference.
The arm64 wheel download is about 1.3 MB. NumPy is its Python dependency;
versions are pinned above. This Python-3.9-compatible pin is host-only, not a
claim of latest release. Remove objects.py and its viewer wiring to remove this
capability; nothing links into the phone app. No third-party source copied.

Rasterio rasterizes the polygon with identity transform, all_touched=False,
uint8 labels 1=card and 2=surroundings. Default GDAL rasterization edge handling
is retained and versioned; do not claim exact parity with a native mobile fill
rule. The saved upright coordinates are used directly (5160×6880). Geometry
partition, complete label coverage and lossless mask encoding are verified.
Continuous polygon area and raster assigned-pixel counts are separate fields.
`objects.json` is a local-coordinate geometry document, not RFC7946 GeoJSON.

Only the original pane shows overlays. Browser Path2D uses even-odd fill for
surroundings with the card as a hole. Selection reads the exact mask at the
sampled original pixel; RGB reads remain isolated from display overlays. Object
selection is available through clicks and accessible buttons. Boundary and
highlights are independently toggled; saved boundary remains proposed.

Inspected sources:
- https://shapely.readthedocs.io/en/stable/manual.html
- https://rasterio.readthedocs.io/en/stable/api/rasterio.features.html
- https://developer.apple.com/documentation/coregraphics/cgpath/subtracting(_:using:)
- https://developer.apple.com/documentation/coregraphics/cgpath/contains(_:using:transform:)
- https://developer.android.com/reference/android/graphics/Path
- https://developer.android.com/reference/android/graphics/Region

Mobile review: CGPath and Android Path/Region supply native equivalents for
these operations. Exported masks should be golden fixtures for a later port;
sloped edges, vertices, on-boundary points and antialiasing need parity checks.
No mobile port or device validation is part of this step.

## Read-only boundary assessment

`boundary_review.py` writes separate diagnostics under baseline/boundary-review.
It never updates source images, saved corners, masks or rectification. Uses
SciPy 1.13.1 (BSD-3-Clause) map_coordinates, gaussian_filter1d and find_peaks;
Matplotlib 3.9.4 (Matplotlib license) renders diagnostic plots. These are host
analysis dependencies, isolated and pinned in boundary-requirements-macos-py39.txt;
remove the assessment script/environment to remove them. No borrowed code.
SciPy wheel about 30.3 MB; no mobile binary dependency is introduced.

Sources inspected:
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.map_coordinates.html
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.gaussian_filter1d.html
- https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html

The experiment uses 81 stations over the central 80% of each edge, +/-3 nominal
mm corridors, three smoothing scales, and paired .25/.5/1 mm patches centered
2 mm inside/outside at three positions per edge. Scales parameterize this
capture experiment; they are not universal thresholds or optical resolution
claims. Card coordinates outside the card are projective extrapolations, not
physical paper measurements. Bilinear source sampling subtracts half a pixel
from edge-origin coordinates for scipy's center-index convention.

All eligible local maxima are retained as image-transition candidates with
source and rectified positions. None becomes a corrected physical boundary.
Corner crops are qualitative diagnostics; straight-edge profiles exclude corner
strata. Texture summaries include printing/illumination, not isolated material
properties. Raw profiles, script/input hashes and parameters remain available.

## Versioned boundary display

Default server startup verifies and serves existing artifacts without rewriting
them. `prepare.py --baseline PATH` is a separate explicit preparation command; rerun
hash-linked experiments if those derivatives change.

The orange observed contour comes from `boundary-v1/geometry.json`. The server
serves its manifest, mask and separate assessments. Before rendering, the browser
verifies schema, source lineage, native fidelity, geometry identity and all three
artifact hashes. A missing or invalid dataset disables the contour without
substituting the saved quadrilateral. Saved partition highlights and linked
rectification retain their original provenance.

The first dataset has no local findings yet. This means unassessed. Historical
whole-image reviews remain in their run folders and do not determine local
acceptance. See `References/contracts/id-cadastral-boundary.md` for the schema,
ring locations, versioning and the next assessment slice.

## Local macOS host operation

`serve.py` requires explicit baseline and boundary directories. `--port` defaults
to 8765; binding is loopback only. Startup validates the complete dataset and
source lineage, verifies retained browser derivatives, snapshots allowlisted
response bytes, and rechecks validation. Restart explicitly to load a new dataset.
No mutable file is reopened to supply response content after admission.

Run the server tests with the pinned Python environment and
`Tools/PixelViewer/test_server.py`; run browser admission tests with
`node Tools/PixelViewer/test-boundary-dataset.cjs`.


## Native edge candidates

Add `--edges PATH` to serve a versioned `Tools/CardEdges` package. Admission uses
its shared validator against the boundary dataset's exact source hash map; the
server retains the admitted bytes and exposes only manifest, chains, points and
offsets routes. Neither the captured raster nor accepted geometry is rewritten.
The browser verifies artifact hashes and reads the package's numeric NPY arrays
without expanding coordinates into JSON. The NPY reader deliberately accepts
only v1 little-endian int32 points and int64 offsets in C order.

The EdgeDrawing candidate overlay and orange GrabCut contour have independent
controls and both default off. The original opens unobstructed. Edge colors use
the currently retained GrabCut mask as an explicitly labeled display reference:
pink inside, blue outside. Every segment is classified using its midpoint mask
pixel; strokes split at color changes without moving or dropping any segment.
This coloring does not accept the GrabCut perimeter or classify material. A
missing verified mask makes this overlay unavailable; no replacement is inferred. Every chain vertex is rendered at its original pixel
center (integer index + 0.5); no chain simplification is applied. Singleton chains render as a dot at the retained
center; two-point chains render their sole segment. Clicking within
eight display pixels of a retained vertex selects its chain in yellow and shows
ID, point count, source-pixel length, bounds and nearest source pixel. This hit
target is presentation behavior, not a detector tolerance or an accepted edge.

Left-edge and bottom-shadow navigation are display bookmarks bound to the exact
retained baseline HEIC hash. Their source positions come from the existing
`left-boundary-diagnosis` and `bottom-boundary-diagnosis` artifacts. They remain
disabled for other sources and do not initialize, constrain or rerun detection.
The damage screenshot has no registered source location and gets no invented
bookmark. No candidate is automatically promoted to the physical perimeter.

Run `node Tools/PixelViewer/test-edges.cjs` for numeric-array and pixel-center
rendering checks, alongside the existing server and rectification tests.


## Exact edge topology

Add `--topology PATH` for a `Tools/CardTopology` dataset. Admission uses the
shared validator, exact source hash map and (when `--edges` is present) exact
edge-manifest hash. All admitted files are served from immutable memory under
`/topology-` routes. The browser checks the needed artifact hashes again.

The topology layer defaults off. Endpoints and junctions display explicit node
markers. Connected component and enclosed-face modes display only the selected
feature, chosen by source-image click or numeric feature ID. Components retain
all path vertices and isolated nodes. Enclosed faces retain every exterior and
interior ring vertex; holes are excluded from point selection. These geometric
faces have no inferred material role. Native index coordinates, including exact
fractional intersections, map to the viewer by adding 0.5 on both axes. Gaps are
not bridged. An eight-display-pixel hit target affects selection only.

Run `node Tools/PixelViewer/test-topology.cjs` for fractional coordinates,
unsimplified rendering, isolated components, hole-aware selection, and invalid
array rejection. Server tests cover topology source/edge lineage, altered bytes,
immutable responses, and route admission. Browser rendering remains a separate
check against the retained native dataset.

## Task-based workspace

The viewer retains both image canvases and their live state while changing only
its tool panel: Inspect (linked pixel readouts), Layers (display controls), Measure
(retained baseline distances/models), Analyze (selected objects/edges/topology and
comparison reports), and Data (all processing provenance and exports). The active
layer legend is always visible. Dataset ownership stays explicit: the working
perimeter is not the perimeter used by the retained measurement baseline.

`workspace.js` moves existing DOM controls instead of cloning them, preserving
handlers and state. It checks that all pre-existing controls/links remain connected.
Tab changes do not change image versions, zoom, pan, selection or checkbox values.
Arrow keys, Home and End navigate the tab bar. Comparison reports open separately
so they do not replace the live workspace.

Verified in browser: all 54 loaded controls/links retained; all five tabs preserve
zoom/pan/pinned point/edge and topology selections/input values; measurement
selection and radius toggle work; legend tracks toggles; interior GeoTIFF, diagonal,
model and edge-data links remain accessible. No console errors. Existing Python
viewer tests and JavaScript admission/geometry suites pass. No analysis data or
processing algorithms changed for this presentation refactor.

Pink/blue edges, diagonals, side lines/3–4–5, and corner radii have permanent
controls above the image workspace in every tab. They are the original input
nodes and handlers, not duplicate controls. Browser verification checks actual
visibility across all five tabs and rendered-image changes when pink edges and
diagonals are toggled; presence in the DOM alone is not sufficient acceptance.

`check-workspace.js` is a repeatable real-browser regression check for the complete
workspace. With an installed Playwright CLI session already open at the local
viewer, run `playwright-cli run-code --filename Tools/PixelViewer/check-workspace.js`
(add the session flag when using a named session). It checks all five tabs retain
inspection state, the four permanent overlay controls stay visible, each overlay
changes the actual canvas and restores it when disabled, and the radius/3–4–5
diagnostics remain present. It restores checkbox values. Run the existing Python
and JavaScript suites as well; this visual behavior check does not establish
physical boundary accuracy.
