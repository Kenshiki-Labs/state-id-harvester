# One gate

## Feature

`npm run check` is the whole gate for this repository, and CI's python and web jobs run its two halves
(`.github/workflows/ci.yml`). A contributor runs it before pushing to dev; a green local run means a
green CI run. It stops at the repository: the harvest workflow and publication are separate.

## Test plan

- `npm run check` in a clean clone of dev with unpushed commits: the SDLC check, every Python step and
  every web step run, and the command exits 0.
- CI on the push: the python job runs `npm run check:python`, the web job `npm run check:web`, and
  both upload their coverage as before.

### Adversarial

- A code commit without a feature doc fails `check:sdlc` locally; in CI (`$CI` set) it is skipped,
  because CI's checkout may lack `origin/dev`.
- No uv on PATH: `scripts/uv.sh` installs exactly uv 0.13.5 under `~/.cache/kenshiki/uv-0.13.5`,
  outside the repository, so `uv build` never packs a tool environment (it refuses a venv's absolute
  symlinks, which is how this was found).
- Each step runs under `set -euo pipefail`, so the first failing step fails the half and the gate.

## Changes

- 0114607: root package.json with check, check:sdlc, check:python and check:web; the CI jobs' inline
  steps move, unchanged and in order, into scripts/check-python.sh and scripts/check-web.sh;
  CONTRIBUTING.md names npm run check. Verified with `npm run check` in a clean clone.

## Review

- 0114607 reviewed: each CI step now exists once, in the two scripts; the workflow keeps only setup and
  artifact uploads.
