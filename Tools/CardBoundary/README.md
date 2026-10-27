# Native observed boundary

Run in the isolated host environment:

```sh
Artifacts/gis-baseline-20260911/geotiff-env/bin/pip install --only-binary=:all: -r Tools/CardBoundary/requirements-macos-py39.txt
Artifacts/gis-baseline-20260911/geotiff-env/bin/python Tools/CardBoundary/refine.py Artifacts/gis-baseline-20260911 Artifacts/gis-baseline-20260911/contour-native/new-run
```

Outputs must be new directories. A failed run writes status=failed and null
geometry, with a diagnostic reason. There is no old-quad fallback. Original
images, geometry, mask and GeoTIFF are hash-checked and retained unchanged.

This reuses OpenCV 4.12.0's GrabCut (GC_INIT_WITH_MASK). Seeds are automatic
Shapely buffers of the saved quad, rasterized through GDAL. Mask foreground is
restricted to the component containing the definite foreground core; other
components and holes are counted. GDAL polygonization supplies pixel-edge
vertices; OpenCV contours supply seed-contact diagnostics. Rounded outline is
retained; no manual painting, corner editing or four-point approximation.

## Codified orange method

OpenCV 4.12.0 GrabCut with `GC_INIT_WITH_MASK`, five iterations, RNG seed 0 and
one thread operates on every upright decoded RGB pixel. The seed band is 0.04
times the shortest saved quadrilateral edge: its inward buffer is definite
foreground, the remaining quad probable foreground, its outward buffer probable
background, and the rest of the full frame definite background. Shapely builds
buffers and Rasterio rasterizes seeds. Four-connected foreground containing the
definite core is polygonized by GDAL at native pixel edges, preserving holes and
irregularities without smoothing or polygon simplification.

This orange contour is the current observed-boundary method. Local wear and
damage are features to retain. The owner confirmed physical damage at one
pictured irregularity; this supersedes treating that irregularity as an error
merely because it departs from a straight line. Assessment is local. Earlier
hash-bound reviews remain historical evidence, not blanket rejection of all
segments. The cyan comparison renderer has been removed from the viewer and
future diagnostic crops. Existing historical images remain unchanged.

## Native architecture

1. `native_input.py` verifies retained-file hashes and the upright RGB decode's
   lineage and dimensions. It admits an immutable full-frame RGB array.
2. `refine.py` uses every native pixel. RGB-to-BGR is checked as an exact channel
   reorder. No resize, crop, sampling option, or reduced-resolution fallback is
   available. Automatic seeds come from the prior quad; they remain assumptions.
3. OpenCV GrabCut segments the full frame. Four-connected component selection
   and GDAL polygonization agree on connectivity. Polygon-to-mask round trip
   must reproduce every foreground pixel. Geometry is never simplified.
4. `evaluate.py` independently reloads source samples, verifies hashes, full
   dimensions, identity transform, and the saved mask/polygon relationship.
   Visual acceptance is a separate hash-bound `review.json`, never inferred from
   successful processing or geometric validity.
5. `dataset.py` verifies and packages the retained geometry, mask and separate
   assessments. ID Cadastral consumes that versioned dataset. Diagnostic crops
   and browser zoom are presentation only; neither supplies analysis pixels.

```sh
Artifacts/gis-baseline-20260911/geotiff-env/bin/python Tools/CardBoundary/test_native.py
Artifacts/gis-baseline-20260911/geotiff-env/bin/python Tools/CardBoundary/evaluate.py Artifacts/gis-baseline-20260911 Artifacts/gis-baseline-20260911/contour-native/native
```

The viewer dataset is `boundary-v1`, packaged from the verified
`contour-native/interface-verification` run. Its geometry and mask exactly match
the earlier `contour-native/native` baseline. Earlier reduced-resolution runs in
`contour-experiment` are historical artifacts, not the current analysis path.
Performance measurements describe execution; optimization waits until a usable
result exists. A valid native contour can still include a shadow or edge band;
physical-boundary acceptance requires inspection. No re-rectification occurs.

## Source and dependency record

Inspected 2026-09-11:
- https://docs.opencv.org/4.12.0/d8/d83/tutorial_py_grabcut.html
- https://raw.githubusercontent.com/opencv/opencv/4.12.0/modules/imgproc/src/grabcut.cpp
- https://github.com/opencv/opencv/blob/4.12.0/samples/python/grabcut.py
- https://docs.opencv.org/4.x/d3/dc0/group__imgproc__shape.html
- https://opencv.org/license/

Research selected the official implementation over scanner wrappers that
usually return another quadrilateral. The official interactive example's seed
painting is not used: only library APIs are called, no source files copied.
OpenCV >=4.5 is Apache-2.0; grabcut.cpp retains Intel's BSD-style three-clause
notice. Installed wheel retains upstream/native notices. Python headless wrapper
4.12.0.88 uses NumPy; downloaded arm64 wheel is about 37.9 MB. Complete installed
host environment is pinned in requirements-macos-py39.txt; GEOS/GDAL/Shapely
reuse is documented in Tools/PixelViewer/README.md. Runtime versions used in
polygonization/buffering are recorded by evaluation.json. Compatibility pin is
for Python 3.9, not a claim of latest upstream release.

Removal seam: remove this host tool and viewer candidate routes/controls. No
mobile package or binary is changed. Native OpenCV availability does not prove
runtime or pixel parity on a phone; no mobile implementation claimed here.

## Package the boundary

```sh
Artifacts/gis-baseline-20260911/geotiff-env/bin/python Tools/CardBoundary/dataset.py Artifacts/gis-baseline-20260911 Artifacts/gis-baseline-20260911/contour-native/interface-verification Artifacts/gis-baseline-20260911/boundary-v1
```

Output must not exist. The package contains manifest.json, geometry.json,
mask.png and assessments.json. Geometry identity is its file SHA256. The mask
is byte-preserved; ring ordering and every coordinate remain unchanged.
Assessment findings start empty, meaning unassessed. The location contract is
`References/contracts/id-cadastral-boundary.md`. This slice does not generate
new local measurements or claim physical acceptance.

## Versioned boundary dataset

`dataset.py` packages an existing completed native run without rerunning its
segmentation or changing its geometry. `verify_boundary` independently admits
source hashes, RGB sample hashes, dimensions, native method parameters,
coordinate metadata, and exact polygon-to-mask equality. It reads but never
rewrites the run or its evaluation. `package_boundary(base, run, out)` stages a
complete dataset and publishes it by directory rename under an exclusive
publisher lock. The destination must not exist; failure cleans staged files.

```sh
Artifacts/gis-baseline-20260911/geotiff-env/bin/python Tools/CardBoundary/test_dataset.py
Artifacts/gis-baseline-20260911/geotiff-env/bin/python Tools/CardBoundary/dataset.py Artifacts/gis-baseline-20260911 Artifacts/gis-baseline-20260911/contour-native/interface-verification Artifacts/gis-baseline-20260911/boundary-v1
```

The four artifacts are `manifest.json`, `geometry.json`, `mask.png`, and
`assessments.json`. Geometry preserves every stored vertex, ring order and start
vertex; the mask is copied byte-for-byte. `boundaryId` is SHA-256 of the exact
geometry artifact: compact sorted-key UTF-8 JSON, finite numbers only, followed
by one LF. Its ring table uses `exterior` and `interior-N` identifiers, with N the
stored coordinate-array index. Distance starts at the first stored vertex,
follows that order, and wraps at the ring's full length. Source-pixel distances
are calculated by GEOS without modifying geometry.

The manifest preserves method, parameters, implementation versions, source
hashes, fidelity, and raw run diagnostics. It identifies the candidate by hash
and hashes each artifact. Assessments start with an empty findings array; no
physical locations or local conclusions are invented from run-level integrity.
See `References/contracts/id-cadastral-boundary.md` for the versioned contract.

## Publication and recovery on macOS

The host publisher uses a persistent flock inode and macOS
`renameatx_np(RENAME_EXCL)` (installed SDK `usr/include/sys/stdio.h`, flag 0x4).
Python's rename lacks kernel no-replace semantics; `publication.py` is a narrow
libc binding, not an alternative imaging implementation or dependency.
Existing outputs, including symlinks, are never overwritten. Files and directories
are fsynced. The OS releases the lock after process death. Do not delete the lock
file: its inode coordinates publishers. SIGKILL can leave a hidden private staging
directory; it is never treated as a dataset or automatically deleted on retry.
A post-rename fsync failure preserves complete output and reports uncertain
durability. Inspect that output; do not retry over it.

Processing also occurs in private staging. Only a complete success/failure record
is published. Invalid and nonfinite parameters produce finite failure JSON.
Unsupported platforms fail explicitly; this publication implementation is macOS.

Validation command:

```sh
Artifacts/gis-baseline-20260911/geotiff-env/bin/python -m unittest discover -s Tools/CardBoundary -p 'test_*.py'
```

`validate_dataset.validate_dataset(directory, baseline)` is the server admission
interface. It rejects unsupported schemas/findings, invalid topology, mismatched
ring lengths, traversal paths, artifact symlinks, corrupted masks and source
lineage mismatches. Geometry remains immutable; v1 findings remain unassessed.
