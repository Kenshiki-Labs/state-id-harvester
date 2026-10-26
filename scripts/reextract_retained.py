#!/usr/bin/env python3
"""Refresh one retained jurisdiction without discovery, downloads or source mutation.

The original manifest run/options describe the original harvest. A private refresh
receipt records the new options/fingerprint and explicitly identifies unchanged
legacy documents. Old derivative namespaces and their hash-bound receipts remain.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from state_id_harvester.extract import extract, fingerprint
from state_id_harvester.library import coverage_row, read_manifest, validate_document, verify
from state_id_harvester.models import Document, Manifest, Options
from state_id_harvester.paths import managed_path
from state_id_harvester.seeds import STATE_DOMAINS
from state_id_harvester.storage import atomic_json, digest, now, within

COUNT_FIELDS = (
    "source_documents",
    "relevance_candidates",
    "quarantined_documents",
    "native_images",
    "rendered_pages",
    "rendered_plate_files",
    "card_boundary_candidates",
    "accepted_reference_assets",
    "coverage_status",
)


def counts(documents: list[Document]) -> dict[str, int]:
    assets = Counter(asset.kind for doc in documents for asset in doc.assets)
    return {
        "sources": len(documents),
        "relevant_sources": sum(d.relevance == "candidate" for d in documents),
        "embedded_images": assets["extracted_image"],
        "crop_candidates": assets["card_candidate"],
        "rendered_pages": len(
            {
                (d.download.sha256, a.page_number)
                for d in documents
                for a in d.assets
                if a.kind == "page_render"
            }
        ),
    }


def check_sources(root: Path, documents: list[Document], options: Options) -> None:
    seen: set[str] = set()
    for document in documents:
        download = document.download
        if download.sha256 in seen:
            raise ValueError("Duplicate source SHA would share an extraction target")
        seen.add(download.sha256)
        source = within(root, download.path)
        if not source.is_file() or source.stat().st_size != download.size_bytes:
            raise ValueError(f"Retained source size mismatch: {download.path}")
        if digest(source) != download.sha256:
            raise ValueError(f"Retained source SHA-256 mismatch: {download.path}")
        if download.size_bytes > options.max_pdf_bytes:
            raise ValueError(f"Retained source exceeds PDF byte budget: {download.path}")


def validate_candidate(root: Path, manifest: Manifest) -> None:
    errors = [
        error for document in manifest.documents for error in validate_document(document, root)
    ]
    if errors:
        raise ValueError("Candidate manifest failed asset verification: " + "; ".join(errors[:10]))
    visual = {
        (doc.download.sha256, asset.sha256)
        for doc in manifest.documents
        for asset in doc.assets
        if asset.kind in {"card_candidate", "extracted_image", "page_render"}
    }
    if any(
        (review.source_sha256, review.asset_sha256) not in visual for review in manifest.reviews
    ):
        raise ValueError("Refresh would orphan an existing hash-bound review")


def refreshed_coverage(
    previous: list[dict[str, Any]], manifest: Manifest, jurisdiction: str
) -> list[dict[str, Any]]:
    if sum(old["jurisdiction"] == jurisdiction for old in previous) != 1:
        raise ValueError("Coverage must contain exactly one selected jurisdiction row")
    row = coverage_row(jurisdiction, manifest, [])
    return [
        {**old, **{key: row[key] for key in COUNT_FIELDS}}
        if old["jurisdiction"] == jurisdiction
        else old
        for old in previous
    ]


def document_receipt(before: Document, after: Document) -> dict[str, Any]:
    return {
        "source_sha256": before.download.sha256,
        "download": before.download.model_dump(mode="json"),
        "before_extraction_fingerprint": before.extraction_fingerprint,
        "after_extraction_fingerprint": after.extraction_fingerprint,
        "before_extractor_version": before.extractor_version,
        "after_extractor_version": after.extractor_version,
        "before": counts([before]),
        "after": counts([after]),
        "previous_asset_paths_retained": [asset.path for asset in before.assets],
        "new_asset_paths": [asset.path for asset in after.assets],
        "new_warnings": after.warnings,
        "source_and_download_provenance_unchanged": before.download == after.download,
    }


def check_preserved_assets(root: Path, documents: list[Document]) -> None:
    errors = [error for document in documents for error in validate_document(document, root)]
    if errors:
        raise ValueError("Previous derivative integrity check failed: " + "; ".join(errors[:10]))


def extract_selected(
    root: Path, selected: list[Document], options: Options, implementation: str
) -> dict[str, Document]:
    replacements: dict[str, Document] = {}
    for before in selected:
        after = extract(before.download, str(root), options)
        if after.download != before.download or after.extraction_fingerprint != implementation:
            raise ValueError("Extractor changed source provenance or implementation identity")
        replacements[before.download.sha256] = after
    return replacements


def promote(
    root: Path,
    payload: dict[str, Any],
    coverage: list[dict[str, Any]],
    original_bytes: bytes,
    coverage_bytes: bytes,
) -> list[str]:
    manifest_path, coverage_path = root / "manifest.json", root / "coverage.json"
    if manifest_path.read_bytes() != original_bytes or coverage_path.read_bytes() != coverage_bytes:
        raise ValueError("Manifest or coverage changed concurrently; refresh not promoted")
    try:
        atomic_json(manifest_path, payload)
        atomic_json(coverage_path, coverage)
        errors = verify(root)
        if errors:
            raise ValueError("Promoted manifest failed verification: " + "; ".join(errors[:10]))
    except Exception:
        atomic_json(manifest_path, json.loads(original_bytes))
        atomic_json(coverage_path, json.loads(coverage_bytes))
        raise
    return errors


def manifest_payload(
    original_bytes: bytes, candidate: Manifest, jurisdiction: str
) -> dict[str, Any]:
    original: dict[str, Any] = json.loads(original_bytes)
    replacements = {
        doc.download.sha256: doc.model_dump(mode="json")
        for doc in candidate.documents
        if doc.download.source.discovery_jurisdiction == jurisdiction
    }
    original["documents"] = [
        {**replacements[doc["download"]["sha256"]], "download": doc["download"]}
        if doc["download"]["source"]["discovery_jurisdiction"] == jurisdiction
        else doc
        for doc in original["documents"]
    ]
    original["generated_at"] = candidate.generated_at
    return original


def refresh(root: Path, jurisdiction: str, options: Options, *, max_documents: int = 20) -> Path:
    root = managed_path(root)
    if jurisdiction not in STATE_DOMAINS:
        raise ValueError("Expected a state or DC jurisdiction")
    manifest_path, coverage_path = root / "manifest.json", root / "coverage.json"
    original_bytes, coverage_bytes = manifest_path.read_bytes(), coverage_path.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()
    manifest = read_manifest(root)
    selected = [
        doc
        for doc in manifest.documents
        if doc.download.source.discovery_jurisdiction == jurisdiction
    ]
    if not selected or len(selected) > max_documents:
        raise ValueError("Retained jurisdiction source count is empty or exceeds refresh budget")
    check_sources(root, selected, options)
    check_preserved_assets(root, selected)
    implementation = fingerprint(options)
    if any(doc.extraction_fingerprint == implementation for doc in selected):
        raise ValueError("Refresh target already active; preserve its existing receipt")
    run_id = now().replace(":", "").replace("+0000", "Z")
    receipt_dir = root / jurisdiction / "reprocessing" / run_id
    receipt_dir.mkdir(parents=True, exist_ok=False)
    (receipt_dir / "before-manifest.json").write_bytes(original_bytes)
    (receipt_dir / "before-coverage.json").write_bytes(coverage_bytes)
    replacements = extract_selected(root, selected, options, implementation)
    if fingerprint(options) != implementation:
        raise ValueError("Extraction implementation changed during refresh; manifest not updated")
    check_sources(root, selected, options)
    check_preserved_assets(root, selected)
    documents = [
        replacements[doc.download.sha256]
        if doc.download.source.discovery_jurisdiction == jurisdiction
        else doc
        for doc in manifest.documents
    ]
    candidate = manifest.model_copy(update={"generated_at": now(), "documents": documents})
    validate_candidate(root, candidate)
    coverage = refreshed_coverage(json.loads(coverage_bytes), candidate, jurisdiction)
    payload = manifest_payload(original_bytes, candidate, jurisdiction)
    atomic_json(receipt_dir / "after-manifest.json", payload)
    errors = promote(root, payload, coverage, original_bytes, coverage_bytes)
    refreshed = list(replacements.values())
    receipt = {
        "schema_version": 1,
        "refresh_id": run_id,
        "jurisdiction": jurisdiction,
        "completed_at": now(),
        "status": "verified",
        "implementation_fingerprint": implementation,
        "options": options.model_dump(mode="json"),
        "original_manifest_sha256": original_hash,
        "updated_manifest_sha256": digest(manifest_path),
        "original_harvest_run_id": manifest.run_id,
        "manifest_run_options_preserved_as_original_harvest_provenance": True,
        "unchanged_other_jurisdiction_documents": len(documents) - len(selected),
        "scope": "Selected jurisdiction refreshed; other extraction receipts retained",
        "before": counts(selected),
        "after": counts(refreshed),
        "verification_errors": errors,
        "previous_derivatives_verified_unchanged": True,
        "documents": [document_receipt(doc, replacements[doc.download.sha256]) for doc in selected],
        "old_derivative_policy": "Preserved unchanged, including existing 600 dpi review plates",
        "new_render_policy": f"{options.dpi} dpi review plates in a separate fingerprint namespace",
        "new_crop_policy": "Original encoded native image bytes; no crop resampling",
        "accepted_cohorts_created": 0,
    }
    atomic_json(receipt_dir / "receipt.json", receipt)
    return receipt_dir / "receipt.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("output"))
    parser.add_argument("--jurisdiction", choices=sorted(STATE_DOMAINS), required=True)
    parser.add_argument("--max-documents", type=int, default=20)
    args = parser.parse_args()
    options = Options(dpi=72, max_render_pages=250, ocr=False)
    receipt = refresh(args.root, args.jurisdiction, options, max_documents=args.max_documents)
    print(receipt)


if __name__ == "__main__":
    main()
