# Cadastre

An auditable reference-library builder for US driver licenses and identification cards
across the 50 states and Washington, DC. The public project contains extraction code,
schemas, official-source citations and hashes, coverage metadata, and reviewed normalized
geometry. Original documents and visual derivatives stay in a separate private vault.
Federal credentials are collected separately under `US_FED`; see [federal collection](docs/federal.md).

Website: <https://cadastre.kenshikilabs.com> · Repository:
<https://github.com/Kenshiki-Labs/state-id-harvester>

Collection, visual review, physical calibration, and credential acceptance are separate
checkpoints. A downloaded brochure does not establish a current design, a complete design
family, or the authenticity of a presented credential. The catalog reports actual gaps;
zero reviewed cohorts means no reviewed runtime template is available.

## Run the collector

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). No browser or model is used.

```sh
uv sync --locked --dev
uv run state-id-harvester harvest --all --ocr
uv run state-id-harvester verify
uv run state-id-harvester export-catalog
uv run python scripts/build_public_catalog.py
uv run python scripts/check_publication.py
```

Use `--states FL TX WA VA PA NE AK` for a bounded collection. Optional `SERPER_API_KEY`
or `BRAVE_API_KEY` enables four searches per selected jurisdiction. Without a key,
curated PDFs and bounded official-page discovery still run. Install Tesseract for `--ocr`
(`brew install tesseract` or `sudo apt-get install tesseract-ocr`). Raw OCR observations
retain their origin and confidence and never automatically become runtime rules.

Large official publications require an explicit download budget. West Virginia's
2025 license comparison poster exceeds the default 35 MiB limit:

```sh
uv run state-id-harvester harvest --states WV --max-pdf-bytes 67108864
```

The transport still checks both declared and actual streamed byte counts. Follow live
agency hub links when source URLs move; a failed request alone does not establish a WAF
block. Archived copies require separate archival provenance and are not silently treated
as live agency publications.

For the private local review surface, start:

```sh
uv run python -m http.server 8765 --bind 127.0.0.1 --directory output
```

Open <http://localhost:8765/>. This directory contains original source media and must
remain local or in the private vault. The public Astro website lives in `web/` and
consumes only the allowlisted export in `web/public/data/`.

## Publication and scheduled collection

[Coverage](library/coverage.md) and [citations](library/manifest.json) are public metadata.
Manually recovered sources are recorded separately until catalog integration:
[Arkansas research and preservation record](docs/source-research/AR-2026-10-26.json).
Its originals, discovery pages, review previews, and research notes are retained under
`output/research/AR/` and in a separately indexed private vault backup.
`scripts/build_public_catalog.py` exports an explicit field allowlist; it does not copy
PDFs, raster images, extracted source text, seals, font outlines, or raw PDF resources.
Only accepted, hash-bound cohorts can contribute public normalized geometry. The public
artifact guard checks the static tree before publication.

The **Build reference library** workflow is configured for manual execution and Mondays
at 09:17 UTC. Its enabled/disabled state in GitHub is an operational setting, separate
from this configuration. It requires `CADASTRE_INGEST_KEY`; optional search keys are
repository secrets. It restores private archives, collects all 51 jurisdictions with
OCR, collects original agency HTML gallery images, verifies hashes and parent HTML bindings,
exports reviewed cohorts, uploads a private snapshot, and commits
only public metadata. It publishes no visual GitHub releases or Actions artifacts.

Private compressed archives are split into at most 40 MiB authenticated transport chunks.
Every chunk and reconstructed archive is hash checked. The latest private pointer changes
only after all archive parts have uploaded. To restore an authorized private collection:

```sh
# Obtain CADASTRE_INGEST_KEY through the operator's secret manager; never paste it in Git.
uv run python scripts/vault_sync.py pull output
uv run state-id-harvester verify
```

Authorized visual access is a separate workflow: an application, entity and applicant
authorization review, accepted reference-use terms, and an individually scoped key.
Domain and registration checks support that review; they do not constitute completed KYB.
Automated KYB provider integration and operational authorization remain separate work.
Visible specimen marking and keyed response metadata support attribution; they do not
guarantee tracing after transformation or create statutory immunity.

## Evidence and architecture

The extraction engine preserves original bytes, page geometry, repeated image placements,
PDF masks, native/OCR provenance, composed-page crops, and extraction fingerprints.
Boundary candidates remain unreviewed until a reviewer binds a decision to source and
asset hashes. Nominal ID-1 coordinates do not imply measured physical accuracy.

See [pipeline contracts](SPEC.md), [review instructions](docs/review.md),
[native PDF semantics](docs/pdf-semantics.md), [independent gallery collection](docs/gallery-sources.md),
[publication boundaries](docs/publication.md), and [architecture alignment](docs/architecture.md).
The website follows the headless core and host separation used by Kenshiki SDKs and
Gateway: static Astro presentation, typed observations, isolated Worker storage, and
server-side authorization. It does not integrate a credential acceptance policy into an SDK.

## License

Code is MIT licensed. The code license does not relicense third-party documents or images.
Official publication establishes provenance, not unrestricted redistribution rights.
This project has no affiliation with state issuing authorities or AAMVA.
