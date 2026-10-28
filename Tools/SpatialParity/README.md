# Native spatial-analysis differential checks

This harness compares the production native spatial algorithms with the existing desktop
CardEdges and CardBoundary implementations using synthetic inputs and the SDK's pinned OpenCV.
It does not run a document check or make an authenticity claim.

## Dependency boundary

`Sources/IdentityEvidenceOpenCVBridge/Spatial/Vendor/EdgeDrawing/manifest.json` pins OpenCV contrib 4.12.0 to its Git commit and hashes each
unaltered upstream file. The Apache-2.0 license is retained beside those files. The only local
compilation shim is `precomp.hpp`: upstream's module-wide header imports private core internals
and unrelated ximgproc modules; this translation unit needs public core, imgproc and its own
EdgeDrawing header. The detector implementation is not edited or simplified.

The current mobile OpenCV build does not contain ximgproc. Compiling these sources against the
existing archive adds that algorithm without introducing another OpenCV runtime. `check.py`
verifies the full pinned OpenCV installation before linking, and rejects a dynamically linked
OpenCV library in the resulting standalone macOS executable. The private bridge build records its complete source set, exported C contract and artifact
hashes in its receipt; the verifier rejects source-set drift.

## Reproduce

Use the current recipe-verified capture bridge artifact and an isolated Python environment
with the pinned desktop detector dependencies:

```sh
python3 -m venv /private/tmp/kenshiki-spatial-parity-env
/private/tmp/kenshiki-spatial-parity-env/bin/python -m pip install -r Tools/SpatialParity/requirements-macos-py39.txt
/private/tmp/kenshiki-spatial-parity-env/bin/python Tools/SpatialParity/check.py
```

The harness creates only synthetic pixels and temporary build products, then deletes its build
directory, verifies the current bridge receipt, and runs `check_abi.py` against the actual macOS
bridge. ABI cases cover invalid/truncated/overflowing input, null handling, source immutability,
graph-index overflow refusal before allocation, complete result buffers and concurrent deterministic
execution. `--verify-only` validates source/dependency pins without compiling. It does not read
retained identity captures, send data, download models or install anything on a device.

The desktop reference is the existing `Tools/CardEdges/detect.py`, not a duplicate Python
implementation. Exact ordered int32 point pairs and chain offsets must match for empty,
adjacent-transition, color/curve and minimum-size rasters, including padded source rows.
The dense fixture retains more than 250,000 points exactly. Allocation-free graph tests
admit 12MP/48MP dimensions and reject actual signed-index overflow. These tests do not
establish memory fit or latency at those resolutions on a phone.
Malformed/truncated/overflowing extents are rejected. Source memory and source files must remain
unchanged. Every returned nonempty segment is retained; there is no image reduction, masking,
line fitting, chain simplification or post-detection length threshold.

GrabCut replay calls the existing desktop `refine.segment_native` and `select_foreground`.
Explicit synthetic seed masks exercise full-label and four-connected core-mask equality,
including a retained hole, discarded diagonal island, disconnected/absent core rejection,
row padding, immutable RGB/seeds and invalid extents. Five iterations and RNG seed zero match the existing method; the native harness leaves
OpenCV thread settings untouched, as production does.

`SeedAdapter` is a bounded convex-quadrilateral implementation of the 4%-of-shortest-edge seed
band. It clips inward offset half-planes, constructs rounded outward joins at 16 segments per
quadrant, and rasterizes half-open center scanlines with rounded x intersections. The independent
reference performs the same existing `refine.py` operations directly with Shapely2.0.7/GEOS3.11.4
and Rasterio1.4.3/GDAL3.9.3. Exact masks are compared for axis-aligned, rotated, subpixel,
half-pixel and perspective quads, plus 128 seeded perturbations, in both ring windings. Degenerate,
duplicate, crossed and frame-clipped inputs must be refused. No native GEOS/GDAL dependency is
introduced. These fixtures establish a bounded candidate, not numerical equivalence over every
possible input or physical acceptance of the resulting mask.

The geometric/raster semantics were checked against the pinned upstream descriptions and source:

- [GEOS3.11.4 offset and rounded-join construction](https://github.com/libgeos/geos/blob/3.11.4/src/operation/buffer/OffsetSegmentGenerator.cpp)
- [GDAL3.9.3 polygon scanline rules](https://github.com/OSGeo/gdal/blob/v3.9.3/alg/llrasterize.cpp)

The native seed candidate is local code; neither upstream library is copied or linked. A plain
point-containment test and OpenCV `fillPoly` are not interchangeable with the desktop rasterizer
at pixel-boundary ties. Future changes must pass differential masks rather than visual checks.

The private adapter uses the existing parameter hypothesis from `Tools/CardEdges/config.json`.
The production entry point serializes heavy analysis with a mutex and saves/restores the
calling thread's OpenCV RNG state. It never changes process-wide thread settings.

Pixel-edge polygonization/topology is not implemented here. Native-versus-desktop equality
on synthetic fixtures is not physical boundary accuracy, on-device performance, liveness
or UI acceptance.

The harness compiles the production adapters and pinned EdgeDrawing sources in
`Sources/IdentityEvidenceOpenCVBridge/Spatial`. There is one algorithm implementation;
synthetic desktop parity exercises the source shipped in the private bridge. The
production C entry point checks actual signed OpenCV graph-index representability,
serializes analysis, and restores the calling thread's OpenCV RNG state. There is no
camera-resolution or output-point budget; allocation may still fail. No implicit downsampling
or process-wide thread-setting changes are permitted.

For memory and undefined-behavior instrumentation, run `check.py --sanitizers`. This
compiles the native adapter harness and EdgeDrawing source with ASan/UBSan. The pinned
prebuilt OpenCV archive is not instrumented; this does not claim sanitizer coverage
inside that archive or on a physical iPhone. The built-artifact C ABI checks remain
a separate non-instrumented step of the same command.

The representability guard follows OpenCV4.12's [GrabCut graph allocation expression](https://github.com/opencv/opencv/blob/4.12.0/modules/imgproc/src/grabcut.cpp#L465)
and the pinned `GCGraph` header: signed intermediates, directed-edge indices and the two
sentinel edges must fit `int`. This prevents arithmetic corruption; it is not a promise
that a representable graph fits available memory. No full-resolution phone latency or
peak-memory result is inferred from allocation-free dimension tests.
