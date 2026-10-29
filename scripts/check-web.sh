#!/usr/bin/env bash
# The web half of `npm run check` and CI's web job: every step, in CI's order.
set -euo pipefail
cd "$(dirname "$0")/.."
npm ci --prefix web --ignore-scripts
npm run check --prefix web
npm run check:types --prefix web
npm test --prefix web -- --coverage
npm run build --prefix web
bash scripts/uv.sh sync --locked --dev --no-build --no-install-project
PYTHONPATH="$PWD/src" bash scripts/uv.sh run --locked --no-sync --no-build python scripts/check_publication.py --bundled web/dist
npm audit --prefix web --omit=dev
