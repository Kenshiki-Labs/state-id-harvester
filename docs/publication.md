# Two-tier publication

## Public research and engineering artifacts

The public repository and static website contain code, generated schemas, citation URLs,
source SHA-256 hashes, collection counts, and accepted normalized geometry. Each of the
51 jurisdictions has a row even when collection found no usable source. Source titles
are citation metadata. OCR text, callout transcriptions, extracted images, original PDFs,
font outlines, and state artwork remain private. Public diagrams are independently drawn
geometric illustrations or projections of reviewed geometry; they are not specimen art.

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

## Private collection and reference derivatives

`output/` is ignored by Git. It holds original PDFs, xref streams, native images, page
plates, OCR, candidate crops, reviews, and per-run ledgers. Cloudflare's private
`cadastre-specimens` R2 bucket stores immutable snapshot chunks, visibly marked specimen
derivatives, and private indexes. It has no public bucket URL. The Worker alone resolves
an approved key's scope and serves an authorized derivative.

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

Prepared specimens come only from relevance-candidate documents and remain unreviewed
crop proposals. A visible **SPECIMEN / VERIFICATION REFERENCE ONLY** footer is added
outside the source raster. The original is preserved separately. A bounded resize may
be used for delivery; scale, padding, original-asset hash, derivative hash, source hash,
and source page are recorded. The `state` field denotes discovery jurisdiction, not an
accepted depicted-state classification. No derivative is a physical CAD master.

## Authorization and terms

An applicant provides an organizational email, entity identity, authorized use, and
reference-use attestation. Free-mail/disposable screening and domain or registration
evidence support a manual decision. A UEI, CAGE record or government-looking domain
alone does not establish applicant authority, legal access entitlement, or completed KYB.
No automated KYB provider integration is claimed. Operators must independently review
entity identity and applicant authorization before key issuance.

Per-key delivery receipts use opaque keyed metadata so recipient identity need not be
embedded in the image. Such metadata can be stripped or transformed; it is not a robust
steganographic leak attribution guarantee. Visible marking, clickwrap terms and access
controls do not automatically create legal immunity or transfer redistribution rights.
The rights and distribution basis of each source require review before external delivery.

## Operations

The weekly/manual workflow requires private vault credentials and never publishes visual
GitHub releases or Actions artifacts. A failed private upload prevents the public metadata
commit. No frontend build can read the private bucket directly. Logs and ledgers retained
in a snapshot remain private. Revocation, scope enforcement and access audit belong to
the Worker; client state never authorizes access. Deployment, schedule enablement and
real applicant authorization are explicit operational checkpoints.
