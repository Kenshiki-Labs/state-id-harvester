# Interior working area

Owner-directed continuation of the existing boundary, not another whole-card
detector. Preserve the original mask. Discover the two bottom candidate runs
covering a majority of the prior side (span >= 0.5), order them inward/outward,
and retain every native point. If there are not exactly two, stop with ambiguity.
This scope-specific rule implements the owner's confirmed bottom-shadow working
interpretation; it is not a general shadow classifier or authentication test.

For every native column shared by the two observations, preserve the complete
vertical extent of each transition. Nonoverlapping extents define a band. Clip
the working mask at the inner extent only within the existing bottom search
corridor. Original mask pixels everywhere else must remain byte-identical.
No interpolation, fitted line, smoothing, gap fill, or capture-specific ID selects
the correction. The observed transitions remain open where the evidence ends.

Interior eligibility is deliberately separate: original foreground outside all
four existing search corridors. The inherited corridor width (4% of shorter prior
side) is an exclusion policy, not measured uncertainty or a confidence interval.
Remaining border pixels are excluded from interior analysis, not rejected as card.
Shadow is a working region; unresolved endpoints stay excluded. This lets interior
work proceed without requiring completion of physical-boundary metrology.

Keep the existing rectification and its coordinate mapping. Publish native labels
and a rectified eligibility GeoTIFF, with registration hash. A rectified pixel is
eligible only if every contributing bilinear source-mask weight belongs to the
interior. Nominal mm remain conditional on that existing registration.

Reuse: NumPy native array operations, rasterio.features.shapes/rasterize for exact
pixel polygonization, OpenCV warpPerspective only for derived mask registration,
and CardBoundary native admission/no-overwrite publication. Dependencies already
present; no copied upstream code, new dependency or Swift change. The project-
specific column attribution and owner-directed region policy have no generic OSS
replacement; no new segmentation mechanism is implemented. Removal seam is this
tool and the optional viewer layer. Sources and versions are the existing
CardBoundary/CardRectification dependency contracts.
