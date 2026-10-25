# State ID Harvester

An open, auditable reference-library builder for US driver licenses and identification
cards across the 50 states and Washington, DC. It collects public official documents,
preserves source bytes, extracts images and geometry, and proposes card crops for review.

The library supports document research and topology analysis. Publication on an official
website establishes provenance; it does not establish specimen scale, current design,
complete coverage, or the authenticity of a presented credential.

## Run locally

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). No browser or model is used.

```sh
uv sync --locked --dev
uv run state-id-harvester harvest --all
uv run state-id-harvester verify
uv run state-id-harvester report
open output/index.html
```

Use `--states FL TX WA VA PA NE AK` for a bounded smoke test. The compatibility command
`uv run python harvester.py --states FL TX WA` also works. See `--help` for budgets.
An optional `SERPER_API_KEY` or `BRAVE_API_KEY` enables four searches per selected
jurisdiction. Without a key, curated PDFs and bounded official-page discovery still run.

For raster callouts and hybrid PDFs, install local Tesseract (`brew install tesseract`
on macOS, `sudo apt-get install tesseract-ocr` on Ubuntu) and add `--ocr`. The scheduled
job enables OCR. Extracted text retains its native/OCR origin and confidence.

Browse at <http://localhost:8765/> after starting:

```sh
uv run python -m http.server 8765 --bind 127.0.0.1 --directory output
```

VS Code tasks provide the same server, full harvest, and integrity check.

## Published library and job

[Coverage](library/coverage.md) and the compact [manifest](library/manifest.json) are
committed separately from bulky source PDFs and images. Download all `library-*.tar.gz`
parts and `library-index.json` from the [latest release](https://github.com/Kenshiki-Labs/state-id-harvester/releases/latest),
then restore and verify:

```sh
uv run python scripts/unpack_library.py path/to/downloads output
uv run state-id-harvester verify
```

The **Build reference library** workflow runs weekly on Mondays at 09:17 UTC, or manually
from the Actions tab. It restores the prior release, refreshes sources, discovers new
PDFs, extracts, verifies, updates coverage, and publishes a new immutable snapshot.
Archives are split below release asset limits. The index contains each part's hash and
byte size; restore verifies these before extraction. Prior extractor derivatives are not
duplicated in a newer snapshot. Historical snapshots remain in their original releases.
GitHub may disable schedules after 60 days without repository activity; check Actions
if a scheduled run stops. Configure optional search credentials as repository secrets.

Defaults bound discovery and extraction. Missing, blocked, oversized, and unprocessed
sources are visible in run ledgers. `--refresh` refetches URLs; `--fail-on-gap` requires a
parsed source for every requested jurisdiction. Neither implies reviewed design coverage.

## Evidence and review

Publisher jurisdiction, discovery jurisdiction, and depicted credential jurisdiction
are separate. Extracted images, card-boundary proposals, and feature text start unreviewed.
Accepted depicted-state coverage requires a hash-bound record in `reviews.json`.
Nominal ID-1 coordinates do not imply measured physical accuracy. See `SPEC.md` for the
pipeline contracts and `docs/review.md` for review and cohort export.

## License

Code is MIT licensed. Downloaded source documents and derived images retain their
respective rights and attribution; the code license does not relicense third-party material.
This project has no affiliation with state issuing authorities or AAMVA.
