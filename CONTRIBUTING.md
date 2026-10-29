# Contributing

Contribute public official-source URLs, extraction improvements, or documented reference
reviews. Preserve original sources and cite source pages for every design or feature claim.
Do not contribute customer scans, real personal credentials, restricted materials, vendor
databases, or reconstructed security artwork. Public specimen overlays remain intact.

To add a source, update `GOLDEN_SEED_PDFS` or the official entry points in `seeds.py` and
record why the source is useful. Legacy official hosts require an explicit reviewed entry.
A dead or robots-blocked link is an outcome to report, not a reason to evade access controls.

```sh
npm run check
```

That is the whole gate, and CI's python and web jobs run its two halves (`.github/workflows/ci.yml`),
so a green local run is a green CI run. `npm run check:python` (`scripts/check-python.sh`) runs ruff,
the format check, mypy, pytest with coverage, the schema and publication checks and the build;
`npm run check:web` (`scripts/check-web.sh`) runs the web app's check, types, tests, build, the
bundled publication check and the runtime audit. Both use uv from PATH, or install the CI pin (0.13.5) once into
`~/.cache/kenshiki/uv-0.13.5`.

When changing models, regenerate schemas with `uv run python scripts/export_schemas.py`.
For extractor changes, include mechanical regression tests and inspect affected live-source
output. Test fixtures prove code mechanics; they do not qualify credential authentication.
