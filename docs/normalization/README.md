# ID-1 normalization gate

This step crops and rectifies a complete card to nominal ID-1 coordinates,
then produces a 4280 × 2699 PNG at 50 pixels/mm. Portrait cards retain their
orientation at 2699 × 4280. Rectification and resizing use one source-pixel
warp; the final nominal crop and portrait quarter-turn do not resample.

The host adapter reuses `derive_transform`, `warp_matrix`, and `project` from
`Tools/CardRectification/rectify.py` in the retained Kenshiki Identity SDK.
It requires that implementation's SHA-256 to be
`227a021f1923e9f0ec3434b1b581661f8cea133a65c10030111557909044d690`.
The retained host environment supplies its existing OpenCV, NumPy, SciPy,
Pillow, Shapely, and Rasterio dependencies. This repository does not restore
or modify the SDK tools, or load a model to recognize text.

`card-boundaries.json` records source-image SHA-256 values and clockwise
pixel-edge corners in top-left, top-right, bottom-right, bottom-left order.
The first pass uses visually examined single-card native image extents and
six explicit card-body crops. Native extents can retain small source margins;
they are approximations, rather than physically measured card perimeters.
The crop decisions are source-specific, not a rule that an image of a similar
aspect ratio must contain a card. Baked-in watermarks and annotations remain.

## Recurring batch job

Run from the harvester checkout using the retained host environment:

```sh
PYTHONPATH=src "$HOST_PYTHON" scripts/normalize_references.py \
  --inventory output/id1-normalization/inventory.json \
  --decisions docs/normalization/card-boundaries.json \
  --rectifier "$CADASTRAL_RECTIFIER" \
  --output output/id1-normalization/new-run
```

The inventory has a `rows` array. Each row identifies `state`, `id`,
`source_sha256`, the published `asset_sha256`, and, when recovered,
`original_asset_sha256` and `original_path`. These are retained original
encoded images, not marked public PNGs or already-normalized outputs.
Source and output dimensions, forward/inverse transforms, source lineage,
output hashes, registry hash, and pending references are recorded in the
run's `manifest.json`. Existing run directories cannot be overwritten.
A failed batch is not published as a completed run.

A missing original or missing boundary remains explicitly pending. It does
not become a stretched page, collage, detail fragment, or accepted card.
The first easy pass processed 628 state references: 414 normalized references
cover all 50 states and DC, while 214 remain pending. Of those, 205 require
card boundaries or separation of multiple cards, and nine need their
original-to-reference lineage recovered. These counts describe references,
not distinct designs or completeness of every card depicted within a page.

## Publication preparation

The same gate is available in the existing publication preparation path:

```sh
PYTHONPATH=src "$HOST_PYTHON" scripts/vault_sync.py prepare-specimens \
  output output/prepared-id1 --limit 1000 --federal-limit 0 \
  --rectifier "$CADASTRAL_RECTIFIER" \
  --boundary-decisions docs/normalization/card-boundaries.json
```

Both gate arguments must be supplied together. State assets without a matching
boundary are omitted from that normalized batch and written to
`normalization-report.json`; the gate does not fall back to stretching them.
Canonical analysis PNGs are retained under `id1/`. The separate marked delivery
image may be downscaled and receives the existing reference footer; its footer
is outside the ID-1 card region. The recorded normalization and delivery
transforms describe those separate operations. Federal page-plate preparation
retains its existing behavior. Plain reference preparation without the gate
continues to preserve the source image's original geometry.

Normalization does not establish physical accuracy, credential authenticity,
current-design status, OCR fields, or accepted runtime cohorts. Upscaling does
not add resolved detail. The easy-pass results are local review artifacts;
they do not replace the live reference library automatically.
