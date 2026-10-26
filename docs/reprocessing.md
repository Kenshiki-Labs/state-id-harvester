# Refresh retained source evidence

Use the normal extraction API to refresh one retained state/DC jurisdiction without
web discovery or downloads:

```sh
PYTHONPATH=src uv run --locked --no-sync python scripts/reextract_retained.py \
  --root output --jurisdiction WA
```

The command validates every selected source's retained SHA-256 and byte count
before starting extraction. It also verifies the previous derivative receipts.
It preserves each download's URL, retrieval time, source hash and publisher
provenance. New artifacts use the normal option/implementation fingerprint
namespace. Existing derivatives, including 600 dpi review plates, stay unchanged.

The bounded refresh uses 72 dpi page review previews, disables OCR, and permits
up to 250 page selections per document so native proposals are not omitted by the
previous twelve-page selection limit. These previews are not image masters.
Native image proposals preserve their original encoded bytes and pixel dimensions;
they are neither magnified page crops nor accepted credential boundaries. Existing
source, image, page and byte budgets continue to apply.

A refresh updates only the selected jurisdiction's document records in the private
`output/manifest.json` and its count fields in `output/coverage.json`. Other
jurisdictions and discovery event counts remain unchanged. The manifest's original
harvest run, revision and options remain original-harvest provenance. Exact refresh
options and per-document extraction fingerprints are recorded separately under
`output/WA/reprocessing/<refresh-id>/receipt.json` (substitute the selected code).
The directory retains exact before-manifest and coverage snapshots, an after
manifest, source/derivative paths, before/after counts and verification results.
A mixed corpus must not be described as though every document used the new pipeline.

Source/provenance changes, source budget violations, a changed implementation,
concurrent manifest changes, orphaned reviews and failed asset verification prevent
manifest promotion. Completed refresh targets cannot be overwritten using the same
active fingerprint. Unpromoted derivatives may remain as private artifacts after a
failure; the previous manifest remains authoritative.

After a successful refresh, the operator can run the existing public catalog builder.
Its allowlist exports source metadata and counts; refresh receipts, source text,
images, font programs and private native-object records are not public assets.

## Washington evidence, 26 October 2026 UTC

The five retained Washington PDFs were refreshed independently of the other ninety
state/DC corpus documents. Washington's native image count changed from 36 to 62,
and its crop proposal count changed from 19 to 11. All six administrative screenshot
proposals were removed. All eight bounded benchmark images on physical PDF pages
11–14 of source `d3027774492b8657bb4b712cb5f1218911a4b94602c342fc8a307a98525e4676`
were preserved; the other three proposals are source-native images on page 16.
Discovery jurisdiction does not establish the depicted credential's jurisdiction.
These figures remain unreviewed and create no accepted cohort or physical accuracy claim.
