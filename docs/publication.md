# Public references and protected source evidence

## Public research and engineering artifacts

The public repository and static website contain code, generated schemas, citation URLs,
source SHA-256 hashes, collection counts, and accepted normalized geometry. Each of the
51 jurisdictions has a row even when collection found no usable source. Source titles
are citation metadata. The website also displays indexed, visibly marked PNG reference
derivatives served by the Worker. Original PDFs, raw extracted resources, OCR text,
callout transcriptions, font outlines, and archive contents remain private. Public diagrams
are independently drawn geometric illustrations or projections of reviewed geometry;
they are distinct from the marked specimen references.

`scripts/build_public_catalog.py` derives public files from `output/manifest.json`,
`output/coverage.json`, and accepted `cohorts.json` records. The existing cohort exporter
first validates source-page bindings, visual-asset hashes, accepted reviews, and cohort
identity. Freeform evidence explanations and invariant descriptions are not copied to
the public bundle. Static publication uses an explicit allowlist rather than a copy
followed by attempted deletion of known private fields.

Run `uv run python scripts/check_publication.py` before building or publishing. It rejects
private media extensions, known media signatures, embedded media data URIs, public raw
extraction payloads, unsafe SVG content and symlinks. Every SVG must declare
`data-cadastre-diagram="independent"` or `"reviewed-geometry"`; review remains necessary
to establish that declaration. This is a publication boundary check, not a legal ruling.
For built Astro output, `--bundled` permits imported brand WOFF2 fonts in `_astro/`.
HTML image elements may point only to the exact same-origin
`/v1/specimens/{STATE|US_FED}/{id}` route. Static source images, alternate image
sources, external images, and embedded image payloads remain excluded.

## Protected storage and public reference delivery

`output/` is ignored by Git. It holds original PDFs, xref streams, native images, page
plates, OCR, candidate crops, reviews, and per-run ledgers. Cloudflare's private
`cadastre-specimens` R2 bucket stores immutable snapshot chunks, visibly marked specimen
derivatives, and private indexes. It has no public bucket URL. The Worker alone resolves
the public reference index and serves indexed, visibly marked PNG derivatives
anonymously. Original archives, raw resources and unindexed objects remain protected.

Transport requires an operator secret in `CADASTRE_INGEST_KEY`. Internal GET/PUT requests
use `/internal/objects/<key>` and an Authorization bearer header. Each upload declares
`x-content-sha256`; the Worker checks the digest. Snapshot chunks are at most 40 MiB,
below the Worker's 50 MiB ceiling. The latest index commits after all chunks exist.
Pull checks every chunk, each reconstructed archive, regular-file-only archive members,
and path containment before extraction. Keep operator secrets out of public CI logs.

```sh
uv run python scripts/package_library.py output tmp/private-snapshot
uv run python scripts/vault_sync.py push tmp/private-snapshot
uv run python scripts/vault_sync.py pull output
uv run python scripts/vault_sync.py prepare-specimens output tmp/private-specimens --limit 100
uv run python scripts/vault_sync.py push-specimens tmp/private-specimens
```

Prepared state crops come from relevance-candidate documents and remain unreviewed
proposals. A separately bounded federal pass includes source page plates even when a
state-specific relevance filter quarantines their document. These are labeled
`reference_kind: page_plate`, `source_collection: US_FED` and `credential_format: unclassified`;
they are never represented as reviewed card crops. `--federal-limit` defaults to 30.
A visible **SPECIMEN / VERIFICATION REFERENCE ONLY** footer is added
outside the source raster. The original is preserved separately. A bounded resize may
be used for delivery; scale, padding, original-asset hash, derivative hash, source hash,
and source page are recorded. The `state` field denotes discovery jurisdiction, not an
accepted depicted-state classification. No derivative is a physical CAD master.

## Anonymous reference access and operator authorization

The website, `GET /v1/specimens` catalog, and indexed PNG reference responses are public.
Visitors need no application, KYB, DNS verification, clickwrap acceptance, or API key.
Anonymous delivery is restricted to the visibly marked derivatives named by the reference
index; a public reference URL does not grant access to original source files or snapshots.

Internal ingestion and administrative operations continue to require operator authorization.
Application and key management, where retained for operator workflows, do not gate public
reference browsing. Secrets remain server-side and outside frontend build inputs.

Visible marking identifies a reference derivative. It does not establish authenticity,
physical measurement accuracy, leak attribution, legal immunity, or a transfer of source
redistribution rights. The code license does not relicense third-party documents or images.

## Operations

The weekly/manual workflow requires private vault credentials and never publishes visual
GitHub releases or Actions artifacts. A failed private upload prevents the public metadata
commit. No frontend build can read the private bucket directly. Logs and ledgers retained
in a snapshot remain private. Public index enforcement, protected-operation authorization, and access audit belong to
the Worker; client state never authorizes privileged access. Deployment, schedule
enablement, and operator authorization are explicit operational checkpoints.

## Retaining researched states across scheduled harvests

`docs/source-research/publication-overlay.json` retains citation and reference metadata
for manually researched collections and native agency galleries. The public exporter
validates the overlay before merging it with harvested metadata. Direct-image sources
are publications rather than PDF pages; unknown retrieval dates remain unspecified.
References remain unreviewed and cannot promote geometry into accepted cohorts.

The specimen publisher merges newly prepared references into the existing private
delivery index. It validates the complete batch before upload, preserves existing
immutable keys, and changes the pointer only after all new objects are present. Empty
or repeated batches cannot erase earlier states. Publishers run serially; an invalid
index, hash conflict, or failed upload stops publication. Scheduled metadata commits
push `dev` and `main` atomically to preserve the canonical branch parity.
