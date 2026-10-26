# Native PDF source observations and private review

`document_semantics.py` builds a source-bound page graph from native text spans,
font runs, paint sequence numbers and placed image objects. It keeps repeated
placements separate even when they reuse an image xref. Typography and section
boundaries associate numbered lists and prose with pictured examples. Every
observation retains exact source text, span IDs and a bounding box in unrotated
MuPDF points. These coordinates describe the PDF, not a physical credential.

The module joins `pdf_objects.inventory_page` records by source hash, page,
coordinate system, image xref, placement and stream hash. The canonical inventory
digest and object, placement, paint and native text IDs remain in the result.
Native source components are the primary evidence. Optional OCR is retained as
transcription evidence; spatial native duplicates are linked rather than counted
twice. Uncertain OCR is never promoted into credential fields or field zones.

## Reproduce a private report

Run from the repository with its installed Python dependencies:

```sh
PYTHONPATH=src uv run --locked --no-sync python scripts/audit_pdf_semantics.py \
  output/WA/raw_pdfs/d3027774492b8657bb4b712cb5f1218911a4b94602c342fc8a307a98525e4676.pdf \
  output/reviews/wa-native-semantics/after \
  --pages 11 12 13 14 --native-objects
```

Use any source PDF and explicit page numbers. `--native-inventory FILE.json`
accepts saved inventory records instead of generating them. `--baseline-text`
accepts previous `TextBlock` records; only their local OCR entries are merged.
`--baseline-summary` displays an operator-provided before summary.

The output contains `index.html`, composed page previews, original extracted
image bytes and mask streams, `after.json`, counts and `review-requests.json`.
All files are private review artifacts. Keep them under ignored `output/` and
out of public site assets, Git and releases. Original source bytes stay intact;
the report does not remove annotations baked into source image pixels.

`--expectations FILE.json` compares an explicit source-inspection label set and
writes `benchmark-results.json`. The JSON has `source_sha256`, `label_origin`
and `expected` entries containing `page`, `xref`, `heading_contains` and
`numbered_callouts`. This checks a bounded source association, not general-state
accuracy. Repeated xrefs on one page require more specific labels and currently
fail this benchmark helper rather than choosing a placement silently.

## Optional grounded interpretation

`semantic_review.py` defines a backend-neutral request/proposal contract. No model
backend is called by this command. A human, assistant or external backend can
supply `--review PROPOSAL.json`; its declared origin is preserved. Proposals cite
existing span IDs with exact quotes and existing image placement IDs. Validation
checks source identity, page, quote fidelity and section binding, then derives
evidence coordinates from the native record. Caller-supplied coordinates,
executable predicates and geometry-transfer authorizations are rejected.

The report displays grounded proposals alongside source context. Grounding is a
mechanical source check: the interpretation remains unverified. The contract
preserves unresolved questions and authorizes neither executable validation
rules nor moving printed feature locations between designs. Source facts can
be reviewed and published with their evidence independently of camera testing;
camera detection rates require separate empirical evidence.

## Bounded Washington benchmark

The inspected source is the Washington Liquor and Cannabis Board's
[2018 Responsible Alcohol Sales Training Guide](https://lcb.wa.gov/sites/default/files/publications/licensing/RVP/RVP_Trainers-Guide-English_2018.pdf),
SHA-256 `d3027774492b8657bb4b712cb5f1218911a4b94602c342fc8a307a98525e4676`.
The benchmark uses physical PDF pages 11–14 and nine actual image placements.
Labels came from direct assistant inspection, not independent human ground truth.

On physical page 12 the upper old-design image (xref 32) receives the five
numbered source observations in its section. The two lower images (xrefs 30 and
34) receive the separate 2018 transition context; the old-design numbered list
does not transfer to them. The source's month-level transition language remains
verbatim; the module does not invent an exact issue-date boundary. The report
also separates the two vertical examples, the enhanced-card prose and the
temporary paper example. A prose comparison is not proof of identical field
geometry or ID-1 format.

The earlier output retained only one of page 12's three actual rasters because
of a pixel-size filter. It omitted the numbering/date prose from its feature
categories and promoted some OCR gibberish into field-zone candidates. The new
semantic pass preserves all nine benchmark figures, links duplicate OCR, and
produces source observations without generating field zones or executable rules.
Crop qualification is handled by the separate native-object extraction module.

## Current limits

- Section association uses typography and placement heuristics. Missing or
  overlapping sections cause abstention; unusual reading order needs review.
- Numbered text is grouped, but leader endpoints and precise feature locations
  on a card are unresolved. Captions are not separately classified yet.
- Active clipping, optional-content visibility and individual Form invocation
  occurrences remain unresolved in the joined native inventory. Native vector
  editing and complete Acrobat-style region reconstruction are not implemented.
- Cross-page and cross-source design matching, exact effective-date intervals,
  semantic contradiction resolution and general document understanding are not
  established by this bounded benchmark.
- No accepted cohort, physical calibration, authenticity verdict or camera
  performance measurement is created by the report.
