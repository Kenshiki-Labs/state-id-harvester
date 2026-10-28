# Path appearance assessment

`assess_paths.py` connects retained surrounding-image evidence to assembled
linework. It changes neither image pixels nor path geometry.

## Source attribution

Assembly source-segment indices identify potential native point membership.
Membership is accepted only when that native point is an actual retained path
vertex. This matters when exact noding splits a diagonal segment between paths.
Candidate source runs restrict each crossing lookup. Every native pixel in a
crossing is attributed separately; a partially mapped crossing or one shared
among paths remains insufficient for path comparison. All mappings are retained.

The prior's inward normal orients the source scan axis, so the three bands are
identified as inward neighborhood, inter-transition band and outward neighborhood.
These are spatial roles; inward does not assert known card material.

## Appearance-continuation hypothesis

Two explicit competing explanations are compared:

- The band continues the outward neighborhood's appearance, supporting the
  inward transition under that hypothesis.
- The band continues the inward neighborhood's appearance, supporting the
  outward transition under that hypothesis.

The comparisons use Euclidean distances between the retained mean RGB-sum
chromaticities and between mean absolute adjacent RGB differences divided by
mean channel intensity. The latter is a declared brightness-normalized
directional-variation heuristic. It is not a complete texture descriptor.

At least one strictly closer feature and no opposite preference supports a
hypothesis. Equal distances are neutral, unavailable features do not vote, and
opposite feature preferences are conflicting. Entirely nondiscriminating evidence
is insufficient. Only complete, uncontaminated retained neighborhoods vote.
Raw distances and signed margins remain available. Strict preference does not
establish statistical significance: a tiny margin is not strong evidence.

Band intensity and whether it is darker than both neighbors remain descriptive
scene observations, including when support is incomplete. They never vote by
themselves. A dark exterior-like band is consistent with an exterior-continuation
hypothesis; its physical cause is not established. Colored shadows and distinct
materials can violate the hypothesis. The synthetic colored-shadow test explicitly
demonstrates this limitation instead of pretending color reveals ground truth.

## Coverage and ordering

Per-comparison source positions and band coordinates link every outcome to the
image. Per-path accounting deduplicates identical native locations. Contradictory
observations at one location are conflicting; differing outcomes across a scan
make that scan mixed. Supported and opposed portions anywhere along a path make
its classification mixed, never a majority winner. Uncompared native locations,
ambiguous branches and insufficient neighborhoods remain visible.

Exploratory browser ordering is descending supported minus opposed unique scans,
with full coverage and conflicts alongside it. It is not confidence, probability,
physical-perimeter selection, or a substitute for comparing the same locations.

## Sources and removal seam

Existing evidence, discovery and assembly source contracts were inspected before
implementation. NumPy 2.0.2's BSD-3-Clause vector norms and reductions implement
the arithmetic; its [norm documentation](https://numpy.org/doc/2.0/reference/generated/numpy.linalg.norm.html)
was inspected. OpenCV's [color-conversion documentation](https://docs.opencv.org/4.13.0/d8/d01/group__imgproc__color__conversions.html)
was inspected as an alternative. No new conversion is substituted for retained
evidence: these inputs contain encoded RGB statistics, not a linear-light
calibration. No upstream implementation is copied and no dependency is added.

The handwritten part is the explicit project-specific two-hypothesis comparison,
source-point attribution and evidence accounting. Generic color conversion and
distance libraries do not provide those provenance and ambiguity semantics.
Removal seam: replace `assess_paths`; detection, native pixels, evidence bands,
and assembly remain independent. Parent publication binds all input manifests.

Tests cover flat-color card with darkened background, interior-like band,
darkness-only ambiguity, colored-shadow counterexample, orientation reversal,
contamination, conflicting directional variation, duplicate evidence, exact
native attribution, diagonal noding, ambiguous branches, contradictory paths,
and partial scan support.
