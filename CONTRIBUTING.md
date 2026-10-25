# Contributing

Contribute public official-source URLs, extraction improvements, or documented reference
reviews. Preserve original sources and cite source pages for every design or feature claim.
Do not contribute customer scans, real personal credentials, restricted materials, vendor
databases, or reconstructed security artwork. Public specimen overlays remain intact.

To add a source, update `GOLDEN_SEED_PDFS` or the official entry points in `seeds.py` and
record why the source is useful. Legacy official hosts require an explicit reviewed entry.
A dead or robots-blocked link is an outcome to report, not a reason to evade access controls.

```sh
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv run python scripts/export_schemas.py --check
uv build
```

When changing models, regenerate schemas with `uv run python scripts/export_schemas.py`.
For extractor changes, include mechanical regression tests and inspect affected live-source
output. Test fixtures prove code mechanics; they do not qualify credential authentication.
