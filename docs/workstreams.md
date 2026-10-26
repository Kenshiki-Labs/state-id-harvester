# Delivery workstreams

Only one delivery is active. A workstream is released after its runtime acceptance
checks pass; a commit, local artifact, or green build alone does not make it released.

## Active: finish ID-1 browser delivery

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
  Final maintainability cleanup will be checked on the release revision.
- [x] Deploy and verify every normalized public image hash; verify the original
  658-reference index remains unchanged.
- [ ] Verify live collection pages, image switching, citations, keyboard/focus
  behavior, and mobile layout.
- [x] Keep local and remote `dev` / `main` at the same release revision
  (`7118720` before the browser delivery fix).

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

- [ ] Serve fixed-size WebP thumbnails and modal viewing copies with versioned caching.
- [ ] Preserve full PNG downloads and every reference/canonical hash.
- [ ] Pass adversarial delivery tests, CI, and SonarCloud for the performance fix.
- [ ] Verify actual browser network requests, transfer sizes, and image controls live.

Pending normalization: 214 references. Of these, 205 need card-body boundaries
or separation of multiple cards, and nine need original-to-reference lineage
recovered. Native image extents are approximate source geometry. This pass does
not certify physical perimeter precision, remove embedded annotations, or accept
runtime authentication templates.

## Paused: source classification

Preserve the source-register implementation and its artifacts. The current local
register accounts for 599 source identities: 584 retained, 15 locally missing.
Retained media include 177 PDFs, 117 HTML documents, and 290 original images.
Classification is partial and has not been released. Its document-role labels
remain provisional until the AAMVA reference vocabulary is assessed. No Docling,
Unstructured, OCR, new source downloads, or vector database was introduced.

Resume this delivery after the ID-1 release is accepted. Its next artifact is an
evidence-backed document/section classification register and exception report,
not a claim that all downloaded material is credential-security guidance.

## Deferred dependencies

Domain-specific claim extraction depends on classification. Embedding/vector
index construction depends on validated structured records. Neither is active.
