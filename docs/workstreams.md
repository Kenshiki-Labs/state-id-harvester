# Delivery workstreams

Only one delivery is active. A workstream is released after its runtime acceptance
checks pass; a commit, local artifact, or green build alone does not make it released.

## Released: ID-1 easy pass and browser delivery

- [x] Retain original source assets and original public references.
- [x] Produce and independently verify 414 ID-1 reference derivatives across all
  50 states and DC, including six explicit card-body crops.
- [x] Wire a reusable normalization gate into publication preparation.
- [x] Pass normalization code CI and SonarCloud on `c54a65c`.
- [x] Prepare marked public display derivatives and verify their source lineage.
- [x] Upload and read back all 414 immutable display objects before publishing
  their index pointer.
- [x] Add public normalized delivery and an in-modal Original / ID-1 control.
  Local validation: 253 web tests, 46 targeted normalization/publication tests,
  Astro and TypeScript checks, production build, and bundled-publication guard pass.
- [x] Pass combined release CI, SonarCloud, and artifact-publication checks
  on `ef0b3f2` (Validate run `40411379483`; Sonar analysis
  `350a4fba-dc26-4723-a3fd-fb99c9cd17c1`, gate OK).
  Final cleanup also passes on the deployed `a479b44` revision (details below).
- [x] Deploy and verify every normalized public image hash; verify the original
  658-reference index remains unchanged.
- [x] Verify live collection pages, image switching, citations, keyboard/focus
  behavior, and mobile layout.
- [x] Keep local and remote `dev` / `main` at the same release revision
  (documentation receipts advance all four tips together after deployed `a479b44`).

The 414 derivatives are public as of 2026-10-26T22:23:06Z. Worker version
`65540fca-7820-4704-bf84-156233190de9` runs source `7118720`; CI run
`40411848427` passes and Sonar analysis `c15061bd-ea36-418e-87d5-a00c7f157e42`
has an OK gate and zero open issues. All 414 public PNG hashes were independently
verified; the public 658-reference original index remains SHA-256
`99c20ed1623809de28464439ec8bfdd3890ecc4fc275af7f3b62765394a17743`.
Evidence: `output/id1-publication/{publication-receipt,public-verification,release-ci,release-quality}.json`.

Browser acceptance uncovered an actual delivery defect: gallery thumbnails and
modal views downloaded the same multi-megabyte PNG. The all-state browser audit
was stopped at Kentucky; that partial run is not an all-state pass.

- [x] Serve fixed-size WebP thumbnails and modal viewing copies with versioned caching.
- [x] Preserve full PNG downloads and every reference/canonical hash.
- [x] Pass adversarial delivery tests, CI, and SonarCloud for the performance fix.
  `a479b44`: 274 web tests; Validate `40413361472` passes; Sonar analysis
  `5fc43067-4028-4a55-8adf-6d59b5bd138a` has an OK gate and zero open issues.
- [x] Verify actual browser network requests, transfer sizes, and image controls live.
  All 51 state collection checks pass; federal count remains 30; desktop and
  mobile layouts inspected. 584 real image responses are all successful WebP,
  with zero automatic PNG requests and zero browser page errors. Per-state
  scope is one normalized and original modal, plus source and keyboard checks.
  Durable release evidence: [release-2026-10-26.json](normalization/release-2026-10-26.json).

WebP delivery is live in Worker `aaf5e061-d3d9-4f40-ba9b-071ecc65063a`.
Two fixed profiles scale down without cropping: thumbnail 640 px maximum edge at
quality 82 and modal display 1600 px at quality 90. Cache keys bind the current PNG
hash, profile, and transformation version. The full PNG is fetched only for an
explicit download or detail zoom. Transform failures never silently load a large PNG.
Actual live Washington ID-1 sample: PNG 3,521,633 bytes; thumbnail 31,696 bytes;
modal 133,892 bytes. Original and federal sample transforms also decode correctly,
and full PNG hashes remain exact. Evidence: `output/id1-publication/webp-live-verification.json`.

Pending normalization: 214 references. Of these, 205 need card-body boundaries
or separation of multiple cards, and nine need original-to-reference lineage
recovered. Native image extents are approximate source geometry. This pass does
not certify physical perimeter precision, remove embedded annotations, or accept
runtime authentication templates.

## Active: document ontology and source classification

Resumed at the user's request after ID-1/WebP publication. The bounded design and
next delivery are in [document-ontology.md](document-ontology.md).

- [x] Audit the preserved source register and all 177 PDF source hashes/packets.
- [x] Validate all 302 evidence links in the 63 provisional PDF classifications.
- [x] Verify current AAMVA 2026 authority and distinguish publication roles from
  standards-grounded credential concepts; retain edition-specific references.
- [x] Record ontology entities, domain extraction routes, evidence contracts and
  concrete mixed-document examples.
- [x] Implement strict, frozen Pydantic contracts for ontology records, native PDF
  packets, private storage manifests and registry projections; export JSON schemas.
- [x] Pass 140 focused adversarial tests, including actual-PDF packet comparison.
- [x] Extract a first batch of eight documents across seven collections: 164
  statements, 177 exact anchors and 15 subject scopes, all explicitly unreviewed.
- [ ] Complete final independent correction checks and private R2 upload/readback.
- [ ] Pass full CI and SonarCloud for the typed extraction/storage code.
- [ ] Complete the edition-specific standards crosswalk and corpus classification
  register with explicit exceptions; the rest of the corpus is not yet extracted.

The source register accounts for 599 identities: 584 retained and 15 missing
originals. Retained media include 177 PDFs (4,074 pages), 117 HTML documents and
290 original images. Existing 63 classifications remain provisional, not complete
corpus coverage. One source mislabeled unreadable is a valid image-only PDF;
correct its processing status when importing the old classifications.

The audit and previous extraction artifacts are preserved under
`output/domain-classification/`. The inventory implementation remains uncommitted
until its classification interface is ready for the next bounded code delivery.
Private storage is specified in [document-ontology.md](document-ontology.md):
R2 retains originals, native packets and validated JSON; D1 registry projection is
prepared without a production migration. Vectorize remains deferred.
No Docling, Unstructured, OCR or new harvesting sweep is active.

## Deferred dependencies

Embedding/vector index construction depends on validated structured records.
Pixel annotation cleanup is deferred: retain original, mask and cleaned derivative;
limit removal to reviewed annotations and exclude reconstructed regions from matching.
Neither workstream is active.
