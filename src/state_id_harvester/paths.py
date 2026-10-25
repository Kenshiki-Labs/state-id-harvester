"""Filesystem boundaries for operator-supplied CLI paths."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def managed_path(value: str | Path) -> Path:
    """Permit the checkout and explicit ephemeral run directories, never arbitrary roots."""
    roots = [Path.cwd().resolve(), Path(tempfile.gettempdir()).resolve()]
    runner_temp = os.environ.get("RUNNER_TEMP")
    if runner_temp:
        roots.append(Path(runner_temp).resolve())
    candidate = Path(value).expanduser().resolve()
    if not any(candidate.is_relative_to(root) for root in roots):
        raise ValueError("Path must remain inside the checkout or managed temporary directory")
    return candidate


def contained_path(root: Path, relative: str | Path) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("Path escapes its managed directory")
    return candidate
