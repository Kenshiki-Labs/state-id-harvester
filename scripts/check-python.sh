#!/usr/bin/env bash
# The Python half of `npm run check` and CI's python job: every step, in CI's order.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src"
uv() { bash scripts/uv.sh "$@"; }
run() { uv run --locked --no-sync --no-build "$@"; }
uv sync --locked --dev --no-build --no-install-project
run ruff check .
run ruff format --check .
run mypy src
run pytest --cov=state_id_harvester --cov-report=xml -q
run python scripts/export_schemas.py --check
run python scripts/check_publication.py
uv build --no-build-isolation
