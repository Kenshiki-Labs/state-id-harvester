# Retained rectifier root after the identity SDK fold

## Feature

kenshiki-identity-sdk is now the `kenshiki-identity-sdk/` folder of kenshiki-sdks (owner, 2026-11-18). The
retained rectifier loader's managed-root allow-list names `../kenshiki-sdks/kenshiki-identity-sdk` in place of the
retired sibling checkout. Admission is otherwise unchanged: only a regular `rectify.py` at the pinned SHA-256
loads.

## Test plan

`npm run check`: Ruff, mypy, pytest and the web suite.

### Adversarial

A file outside every managed root, a symlink, or a file with another hash is refused exactly as before.

## Changes

- `2b873d8`: the managed root moves to the folded SDK.

## Review

- `2b873d8` Review: one allow-list entry changes; nothing to simplify. Evidence: `npm run check` (748 Python tests,
  328 web tests).
