"""Adversarial boundaries for the optional publication metadata input."""

from __future__ import annotations

import importlib.util
import sys

import pytest

spec = importlib.util.spec_from_file_location(
    "overlay_io_exporter", "scripts/build_public_catalog.py"
)
assert spec is not None
assert spec.loader is not None
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


@pytest.fixture
def managed_root(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(root))
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    return root


def test_reads_only_bounded_json_and_allows_absent_optional_file(managed_root):
    path = managed_root / "overlay.json"
    assert exporter.read_publication_overlay(path) is None
    path.write_text('{"schema_version": 1, "collections": []}')
    assert exporter.read_publication_overlay(path) == {"schema_version": 1, "collections": []}


@pytest.mark.parametrize("symlink", [False, True])
def test_cli_rejects_escape_before_reading_sources_or_writing_outputs(
    managed_root, monkeypatch, symlink
):
    outside = managed_root.parent / "outside.json"
    outside.write_text('{"private": "must not be read"}')
    supplied = managed_root / "link.json" if symlink else outside
    if symlink:
        supplied.symlink_to(outside)
    monkeypatch.setattr(
        sys, "argv", ["build_public_catalog", "--publication-overlay", str(supplied)]
    )
    with pytest.raises(SystemExit) as rejected:
        exporter.main()
    assert rejected.value.code == 2
    assert not (managed_root / "web").exists()
    assert not (managed_root / "library").exists()


def test_rejects_oversized_input_before_json_decode_or_export(managed_root, monkeypatch):
    path = managed_root / "overlay.json"
    monkeypatch.setattr(exporter, "MAX_OVERLAY_BYTES", 16)
    path.write_bytes(b" " * 17)
    monkeypatch.setattr(sys, "argv", ["build_public_catalog", "--publication-overlay", str(path)])
    with pytest.raises(ValueError, match="size limit"):
        exporter.main()
    assert not (managed_root / "web").exists()
    assert not (managed_root / "library").exists()


def test_rejects_invalid_json(managed_root):
    path = managed_root / "overlay.json"
    path.write_text("not json")
    with pytest.raises(ValueError):
        exporter.read_publication_overlay(path)
