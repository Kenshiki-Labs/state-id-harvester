#!/usr/bin/env bash
# uv for the gate: the one on PATH, or uv 0.13.5 (the CI pin) installed once outside the repository,
# so a tool environment never lands in the source distribution `uv build` packs.
set -euo pipefail
if command -v uv >/dev/null; then exec uv "$@"; fi
tools="${XDG_CACHE_HOME:-$HOME/.cache}/kenshiki/uv-0.13.5"
if [ ! -x "$tools/bin/uv" ]; then
  python3 -m venv "$tools"
  "$tools/bin/python" -m pip install -q --only-binary=:all: uv==0.13.5
fi
exec "$tools/bin/uv" "$@"
