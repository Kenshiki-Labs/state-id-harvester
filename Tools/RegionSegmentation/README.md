# Native region comparison

This host experiment evaluates whether automatic scene regions expose transitions
hidden by the binary GrabCut card mask. It does not replace the accepted dataset,
select a physical card perimeter, or feed rectification. Region meanings remain
unassigned. Shadow and material are not classified.

For a fresh capture, pass `--full-scene-diagnostics` to `experiment.py`. The four
partitions still use every native pixel; diagnostic panels cover the entire source
instead of historical windows. New runs record the exact four-connected adjacency
method already implemented by `adjacency.py`. The historical results below remain
historical and do not describe new captures.

## Preregistered comparison

`experiment.py` admits the verified upright RGB8 raster through CardBoundary's
native source admission. Every pixel participates in each of four partitions:

| Elevation cues | Automatic marker depth |
| --- | --- |
| Luminance gradient | 0.08 |
| Luminance gradient | 0.16 |
| Chroma and relative-texture gradients | 0.08 |
| Chroma and relative-texture gradients | 0.16 |

RGB is converted to CIELAB. Derivative Gaussian sigma is nominally 0.03 mm;
texture Gaussian sigma is nominally 0.15 mm. The implementation converts these
using the mean of the four saved edge pixel/mm ratios, retaining all four ratios.
This is an approximate scene scale, not a spatially varying metric calibration.
The saved corners set scale only: they never impose card labels, a search band,
or a segmentation mask.

Texture is the Gaussian RMS of local relative luminance residuals, with a 0.01
brightness denominator floor. Each gradient cue is divided by its full-scene
99th percentile without clipping. The chroma/texture elevation is their
root-mean-square combination. These settings are experimental, not calibrated
defaults; the two marker depths are a declared sensitivity comparison.

`h_minima` supplies automatic markers. SciPy connected-component labeling and
scikit-image watershed use four-neighbor connectivity. Watershed compactness is
zero; there is no shape regularization. Every pixel receives a positive region
label. A connectedness check verifies one component per region. There are no
manual labels, card-mask constraints, downsampling, or optimized reduced input.
Feature filtering is a recorded derivative; original samples are preserved.

The initial region adjacency graph records region pixel counts, mean Lab and relative
texture, mean boundary elevation, library boundary counts, and pairwise
differences. A library boundary count is not geometric perimeter length; an
elevation weight is not confidence. Lab chroma is not illumination invariant.
Independent evaluation found that `rag_boundary` does not preserve exact
side-sharing adjacency at multi-region junctions. The original run and its graph
remain immutable legacy evidence. `adjacency.py` instead uses
`skimage.graph.RAG(labels, connectivity=1)` and checks that its topology matches
every horizontal/vertical label transition. Each shared unit pixel edge is
counted once, with elevation equal to the mean of its two neighboring pixels.
`rebuild_adjacency.py` publishes corrected graphs separately without changing
retained partitions. This repair establishes graph semantics, not physical-edge
accuracy.

## Evaluation and artifacts

The immutable run retains native label arrays, both elevation rasters, adjacency
JSON, source diagnostic crops, magenta region-boundary overlays, parameters,
source hashes, package versions, and a manifest. Diagnostic windows are
observation-only crops; they do not influence processing. The known cases are
the left seed-limit excursion and three bottom dark-band windows. The top
midpoint is contextual. The owner's confirmed damage screenshot has not been
registered to source coordinates, so preservation of that specific damage cannot
yet be claimed.

The comparison asks whether alternate transitions become visible, not whether
one partition can already be called the true card. In particular, a brightness
change accompanied by similar chroma/texture is only compatible with shadow;
it does not establish the material or physical boundary. Integrity checks and
visual/physical acceptance are separate.

```sh
Artifacts/gis-baseline-20260911/geotiff-env/bin/python Tools/RegionSegmentation/experiment.py BASELINE NEW_RUN_DIRECTORY
Artifacts/gis-baseline-20260911/geotiff-env/bin/python Tools/RegionSegmentation/report.py NEW_RUN_DIRECTORY NEW_REPORT_DIRECTORY
```

For the reviewed comparison, pass `--review PATH_TO_REVIEW_JSON` and
`--adjacency CORRECTED_ADJACENCY_DIRECTORY` to `report.py`. The report verifies
their linkage to the exact experiment manifest. Omit the adjacency argument
while correction is still running; the page explicitly labels original graph
counts as legacy and shows corrected counts as not supplied.

`report.py` verifies manifest hashes for displayed crops and region JSON and
publishes `report.html` into a new sibling directory. It leaves the immutable run
unchanged. Images are ordinary browser display elements; report generation does
not resize or reprocess source pixels. Keep reports and runs local because they
contain credential images.

## Recorded result: no condition selected

The retained `region-comparison/review.json` is bound to the first experiment
manifest and records independent full-label checks and visual observations.
Neither cue family at depth 0.16 retains a region transition in any of the
296 registered left-side rows. Luminance at 0.08 exposes useful left and
bottom-left dark-band transitions, but fragments the bottom-center/right upper
transition among printing/reflection detail and strongly oversegments the top.
Chroma/texture at 0.08 also produces partitions crossing visible edges.

No condition is selected as a boundary replacement. Transition presence is not
ground-truth edge accuracy, and the confirmed damage location remains
unregistered. The four ID-1 sides should be considered together in their shared
nominal card plane when evaluating candidate transitions. However, mapping an
arbitrary quadrilateral to the ID-1 rectangle always supplies a projective fit;
that alone cannot identify which physical transitions are correct. These
constraints do not authorize smoothing observed damage or promoting a result.

## Reused implementation and provenance

No upstream algorithm files are copied or modified. Local code composes public
APIs; the removal seam is this experiment directory and its pinned environment.
Existing CardBoundary source admission/publication is reused.

- **scikit-image 0.24.0**, compatible with Python >=3.9. It is an older pinned
  compatibility release, not a claim to use the newest upstream release. The
  macOS wheel download is approximately 13.4 MB; this is not installed size or
  runtime memory. Watershed internally converts elevation to float64 and
  allocates native-size working arrays.
- [Watershed implementation](https://github.com/scikit-image/scikit-image/blob/v0.24.0/skimage/segmentation/_watershed.py),
  [h-minima](https://scikit-image.org/docs/0.24.x/api/skimage.morphology.html#skimage.morphology.h_minima),
  [region adjacency](https://scikit-image.org/docs/0.24.x/api/skimage.graph.html#skimage.graph.rag_boundary),
  [dependency metadata](https://github.com/scikit-image/scikit-image/blob/v0.24.0/pyproject.toml).
- Broad license BSD-3-Clause. Watershed and filter files include historical
  MIT/Broad Institute and author copyright notices under BSD-3-Clause. Preserve
  the complete installed upstream license in `THIRD_PARTY_LICENSE.txt`, including
  its BSD-2-Clause and MIT exceptions for other package files.
- Dependencies include NumPy, SciPy, NetworkX, Pillow, ImageIO, tifffile,
  packaging, and lazy-loader. `requirements-macos-py39.txt` pins the resolved host
  environment, including inherited raster/geometry dependencies and transitives.

This Python implementation is a local host experiment. Mobile execution and
generalized physical-boundary accuracy have not been established.
