# Surrounding-image evidence

`evidence.py` consumes native RGB8, immutable native edge points, and automatically
discovered candidate source runs. It does not discover or choose an edge itself.

For top/bottom candidates, every native column is visited; for left/right,
every native row. These are source raster axes, not fitted card normals. Each
candidate's contiguous pixels along a scan form a transition range. A chain
crossing the same scan several times retains separate ranges. Duplicate points
are dissolved only in this derived occupancy view; source runs remain unchanged.

Overlapping transition ranges form occupancy components. Every overlapping pair
is retained, as is every alternative pairing between consecutive components.
This prevents nested ranges from hiding another competing transition.
The pixels strictly
between them determine the neighborhood depth. Equally deep bands before the
first and after the second transition provide surrounding evidence. Transition
pixels remain referenced but are excluded from these comparison bands. Native
pixel counts, requested/available source ranges, RGB means and population
standard deviations, mean-channel intensity, RGB-sum chromaticity and adjacent
pixel differences are recorded. Every pixel and every adjacent pair in the
available interval contributes. No image interpolation or smoothing is applied.

The bands can include additional transitions; all such crossings are listed per
band. A transition in the between-band suppresses descriptive cross-comparison.
Pair eligibility requires complete bands with no other transition in any band.
These are spatial neighborhoods,
not asserted homogeneous material samples. A single scan's adjacent difference
describes directional variation, not complete two-dimensional texture. RGB is
encoded image color, not calibrated radiance or inferred ink chemistry.
All-zero RGB pixels have undefined chromaticity and their count is explicit.
RGB and chromaticity distances are descriptive, not likelihoods or classifiers.

Missing transitions, single transitions, overlap, touching transitions and
clipped neighborhoods are explicit. A clipped band retains all available pixels
but does not receive complete comparison status. No candidate is selected.

## Source-first implementation

Existing `Tools/CardEdges/evaluate.py` and `Tools/CardMeasurements/measure.py`
were inspected for coordinate and all-native measurement conventions. Their
capture-specific diagnostics do not supply candidate selection to this module.

Inspected upstream NumPy 2.0 documentation for [mean](https://numpy.org/doc/2.0/reference/generated/numpy.mean.html)
and [diff](https://numpy.org/doc/2.0/reference/generated/numpy.diff.html).
The existing pinned NumPy 2.0.2 implementation supplies reductions, sorting,
unique occupancy and differences (BSD-3-Clause). Float64 conversion precedes
differences to prevent unsigned RGB wraparound. No upstream source is copied.
SciPy 1.13.1 [Wasserstein distance](https://docs.scipy.org/doc/scipy-1.13.1/reference/generated/scipy.stats.wasserstein_distance.html)
was considered; mean color distances and complete interval references suffice
for this descriptive slice, so it is not used here.

The handwritten portion is source-coordinate assembly and evidence packaging;
the general numerical libraries do not provide this project's candidate-run,
native scan, completeness and source-provenance contract. No dependency is added.
Removal seam: replace `assess_surroundings`; discovery and original edge datasets
remain independent.

Validation: `python -m unittest Tools.PerimeterCandidates.test_evidence` covers
complete native interval participation, RGB arithmetic, undefined black
chromaticity, geometry-derived support, clipping, overlap/adjacency, transpose
equivalence, disjoint crossings, empty candidates and invalid native coordinates.
