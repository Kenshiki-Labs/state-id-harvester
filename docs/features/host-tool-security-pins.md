# Host tool security pins

## Feature

Security updates to the pinned dependencies of the local host tools under `Tools/`, which run on the
operator's Mac outside the gate (`pyproject.toml` excludes `Tools/`). This record covers filelock 4.2.1
for AppleMaterials (Dependabot #7) and Pillow 13.0.0 for TemporalEvidence (Dependabot #6, superseded).
It stops there: the other Python 3.9 tool manifests and AppleMaterials keep their Pillow pins, and their
open Pillow alerts remain.

## Test plan

- filelock: resolve `Tools/AppleMaterials/requirements-macos-py311.txt` with pip on Python 3.11
  (`pip install --dry-run --only-binary=:all: -r ...`); it must resolve with torch 2.14.0 and exit 0.
- TemporalEvidence: in a fresh Python 3.11 environment with `requirements-macos-py311.txt` installed,
  `python -m unittest discover -s Tools/TemporalEvidence -p 'test_*.py'` passes, and
  `python Tools/Cadastral/check.py --group temporal` runs the same suite and exits 0.
- Cadastral launcher: `python -m unittest test_launch` in `Tools/Cadastral` passes.
- `npm run check` passes.

### Adversarial

- Pillow 13.0.0 requires Python >=3.11 (PyPI `requires_python`), so Dependabot #6's bump of the py39
  manifest would fail to install on the tool's Python 3.9. The manifest is renamed to py311 rather than
  left naming a Python it cannot install on.
- `check.py --group temporal --baseline DIR` must not select the Python 3.9 geometry environment:
  `test_temporal_checks_use_invoking_python_even_when_baseline_supplied` asserts the invoking Python
  with and without `--baseline`.
- Report provenance: `analyze.py` records `pillowVersion` and `pythonVersion` in each report, so a
  package built on the new environment is distinguishable from an older one.

## Changes

- abd86c2: merge Dependabot #7, filelock 3.32.6 to 4.2.1 in AppleMaterials (Python 3.11), fixing its
  open filelock advisories. Verified by the pip dry-run resolve above; the AppleMaterials test suite was
  not run.
- ba45284: move TemporalEvidence to Python 3.11 with Pillow 13.0.0 (NumPy 2.0.2 unchanged); the
  temporal check lane uses the invoking Python, matching `launch.py`'s temporal viewer; READMEs and
  the pyproject comment updated. Verified on Python 3.11.15: TemporalEvidence 45 tests pass,
  `check.py --group temporal` passes, Cadastral `test_launch` 9 tests pass.

## Review

- ba45284 reviewed: one assignment in `check.py` replaces the geometry fallback; the guard test keeps
  both cases and changes only the expected interpreter. No duplicated logic added; the README pointers
  name the one manifest.
