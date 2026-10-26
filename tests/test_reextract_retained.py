"""A retained-source refresh must preserve provenance and unrelated manifest rows."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pymupdf
import pytest

from state_id_harvester.extract import extract
from state_id_harvester.library import coverage, read_manifest, verify
from state_id_harvester.models import Download, Manifest, Options, Source
from state_id_harvester.storage import atomic_json, digest

spec = importlib.util.spec_from_file_location(
    "reextract_retained", Path("scripts/reextract_retained.py")
)
assert spec is not None
assert spec.loader is not None
refresher = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = refresher
spec.loader.exec_module(refresher)


def source_document(root: Path, code: str) -> Download:
    path = root / code / "raw_pdfs/source.pdf"
    path.parent.mkdir(parents=True)
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((20, 30), "Driver license reference microprinting ultraviolet")
        pixels = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 229, 146), False)
        pixels.clear_with(160)
        page.insert_image(pymupdf.Rect(40, 80, 269, 226), stream=pixels.tobytes("png"))
        doc.save(path)
    return Download(
        source=Source(
            discovery_jurisdiction=code,
            url=f"https://example.gov/{code}.pdf",
            discovered_via="synthetic refresh mechanics fixture",
        ),
        final_url=f"https://example.gov/{code}.pdf",
        retrieved_at="2026-10-25T00:00:00Z",
        sha256=digest(path),
        size_bytes=path.stat().st_size,
        path=path.relative_to(root).as_posix(),
        content_type="application/pdf",
        publisher_host="example.gov",
        publisher_jurisdiction=code,
    )


def library(root: Path) -> Manifest:
    original_options = Options(dpi=100, max_render_pages=0, detect_boundaries=False)
    documents = [
        extract(source_document(root, code), str(root), original_options) for code in ["WA", "AL"]
    ]
    manifest = Manifest(
        generated_at="2026-10-25T00:00:00Z",
        run_id="original-harvest",
        source_revision="original-revision",
        requested_jurisdictions=["WA", "AL"],
        options=original_options,
        documents=documents,
        reviews=[],
    )
    atomic_json(root / "manifest.json", manifest.model_dump(mode="json"))
    rows = coverage(manifest, [])
    next(row for row in rows if row["jurisdiction"] == "WA")["discovery_events_this_run"] = 7
    atomic_json(root / "coverage.json", rows)
    return manifest


def test_refresh_preserves_downloads_original_assets_and_other_jurisdictions(
    tmp_path: Path,
) -> None:
    before = library(tmp_path)
    original_payload = json.loads((tmp_path / "manifest.json").read_text())
    for document in original_payload["documents"]:
        document["download"]["source"].pop("credential_format")
    atomic_json(tmp_path / "manifest.json", original_payload)
    old_assets = {
        asset.path: digest(tmp_path / asset.path)
        for doc in before.documents
        for asset in doc.assets
    }
    old_coverage = json.loads((tmp_path / "coverage.json").read_text())
    options = Options(dpi=72, max_render_pages=250, ocr=False)
    receipt_path = refresher.refresh(tmp_path, "WA", options)
    after = read_manifest(tmp_path)
    receipt = json.loads(receipt_path.read_text())
    assert after.documents[0].download == before.documents[0].download
    assert after.documents[1] == before.documents[1]
    payload = json.loads((tmp_path / "manifest.json").read_text())
    assert payload["documents"][1] == original_payload["documents"][1]
    assert payload["documents"][0]["download"] == original_payload["documents"][0]["download"]
    assert after.run_id == before.run_id
    assert after.options == before.options
    assert after.source_revision == before.source_revision
    assert after.documents[0].extraction_fingerprint != before.documents[0].extraction_fingerprint
    assert all(digest(tmp_path / path) == sha for path, sha in old_assets.items())
    assert receipt["before"]["crop_candidates"] == 0
    assert receipt["after"]["crop_candidates"] == 1
    assert receipt["unchanged_other_jurisdiction_documents"] == 1
    assert receipt["previous_derivatives_verified_unchanged"] is True
    assert not verify(tmp_path)
    new_coverage = json.loads((tmp_path / "coverage.json").read_text())
    assert (
        next(row for row in new_coverage if row["jurisdiction"] == "WA")[
            "discovery_events_this_run"
        ]
        == 7
    )
    assert [r for r in old_coverage if r["jurisdiction"] != "WA"] == [
        r for r in new_coverage if r["jurisdiction"] != "WA"
    ]


def test_modified_source_blocks_all_extraction_and_manifest_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = library(tmp_path)
    source = tmp_path / before.documents[0].download.path
    data = bytearray(source.read_bytes())
    data[-1] ^= 1
    source.write_bytes(data)
    original = (tmp_path / "manifest.json").read_bytes()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("No extraction before every source passes preflight")

    monkeypatch.setattr(refresher, "extract", forbidden)
    options = Options(dpi=72)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        refresher.refresh(tmp_path, "WA", options)
    assert (tmp_path / "manifest.json").read_bytes() == original


def test_changed_implementation_during_refresh_is_not_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library(tmp_path)
    original = (tmp_path / "manifest.json").read_bytes()
    actual = refresher.extract

    def drift(download: Download, root: str, options: Options):
        result = actual(download, root, options)
        monkeypatch.setattr(refresher, "fingerprint", lambda opts: "changed-code")
        return result

    monkeypatch.setattr(refresher, "extract", drift)
    options = Options(dpi=72, max_render_pages=1)
    with pytest.raises(ValueError, match="implementation changed during refresh"):
        refresher.refresh(tmp_path, "WA", options)
    assert (tmp_path / "manifest.json").read_bytes() == original


def test_concurrent_manifest_change_is_preserved_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library(tmp_path)
    actual = refresher.extract
    concurrent = b""

    def change_manifest(download: Download, root: str, options: Options):
        nonlocal concurrent
        result = actual(download, root, options)
        path = Path(root) / "manifest.json"
        record = json.loads(path.read_text())
        record["run_id"] = "another-writer"
        atomic_json(path, record)
        concurrent = path.read_bytes()
        return result

    monkeypatch.setattr(refresher, "extract", change_manifest)
    options = Options(dpi=72, max_render_pages=1)
    with pytest.raises(ValueError, match="changed concurrently"):
        refresher.refresh(tmp_path, "WA", options)
    assert (tmp_path / "manifest.json").read_bytes() == concurrent


def test_post_promotion_verification_failure_restores_previous_manifest_and_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library(tmp_path)
    original = json.loads((tmp_path / "manifest.json").read_text())
    old_coverage = json.loads((tmp_path / "coverage.json").read_text())
    monkeypatch.setattr(refresher, "verify", lambda root: ["Injected asset verification failure"])
    options = Options(dpi=72, max_render_pages=1)
    with pytest.raises(ValueError, match="Promoted manifest failed verification"):
        refresher.refresh(tmp_path, "WA", options)
    assert json.loads((tmp_path / "manifest.json").read_text()) == original
    assert json.loads((tmp_path / "coverage.json").read_text()) == old_coverage
