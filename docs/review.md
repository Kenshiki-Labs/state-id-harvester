# Reviewing a reference

Run `uv run state-id-harvester harvest --all --ocr`, then browse `output/index.html`.
For a local HTTP address, run:

```sh
uv run python -m http.server 8765 --bind 127.0.0.1 --directory output
```

Open <http://localhost:8765/>. The contact sheet links each proposal to its full page and
retained source PDF. It is a review surface, not an automatic assertion of card identity.

## Review the source before the crop

1. Confirm the source's issuer, publication date, specimen label, and design generation.
   A page in a Texas training guide may depict another state's credential.
2. Inspect all four boundaries. Images may be stretched, composited, watermarked, or show
   a detail panel. Multiple card faces may share one raster object. Rounded corners and
   clear windows can confuse contours.
3. Compare the composed page to the native image: masks, vector overprints, arrows, and
   annotations may change the specimen's visible appearance. Crops intentionally retain
   overlays; they do not reconstruct an imagined clean credential.
4. Inspect text method and OCR confidence. Link callouts using source evidence; do not move
   text from an external callout into an on-card zone without a reviewed annotation.
5. Treat relative positions as specimen topology. Nominal millimeters do not establish
   physical precision. Calibration requires independently measured physical specimens,
   ground truth, acquisition details, cohort variation, and held-out validation. A fixed
   count of three or five cards does not guarantee a particular tolerance.

## Record a depicted-state decision

Edit `reviews.json`, an array validated by `schemas/reviews.schema.json`. Each entry needs
`source_sha256`, `asset_sha256`, `depicted_jurisdiction`, `credential_type`,
`design_generation`, `side`, `status`, `reviewer`, `reviewed_at`, and an evidence explanation.
Hashes are shown in the contact sheet. Use a named design generation supported by the
source; a filename year or download date alone does not establish a generation.

Re-run a cached harvest to apply review decisions to coverage. Accepted coverage counts
assets, not complete front/back design families. Rejecting a proposal never deletes its source.

## Cohort interchange

Edit `cohorts.json` using `schemas/cohorts.schema.json`, then run:

```sh
uv run state-id-harvester export-catalog
```

Every cohort, zone, and feature observation requires source-page and accepted visual-asset
hash bindings. Date ranges may overlap or remain unknown. The routing helper preserves
multiple candidates. Feature observations name their acquisition modality: visible, tilt,
transmitted light, UV, tactile, or barcode. Missing evidence for a modality means unobserved.
Do not turn a failed optical observation into a counterfeit finding without a separately
validated capture method and decision policy.

Public collection starts with empty accepted reviews/cohorts. This is deliberate:
extraction success does not substitute for review or physical acceptance.
