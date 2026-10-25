"""Coverage, offline contact sheet, and integrity validation."""

from __future__ import annotations

import html
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from .models import Document, Event, Manifest, Review
from .paths import managed_path
from .seeds import FEDERAL_CODE, STATE_DOMAINS
from .storage import atomic_json, digest, within


def validate_document(document: Document, root: Path) -> list[str]:
    errors: list[str] = []
    records = [(document.download.path, document.download.sha256, document.download.size_bytes)]
    records.extend((a.path, a.sha256, a.size_bytes) for a in document.assets)
    for relative, sha, size in records:
        try:
            path = within(root, relative)
            if not path.is_file() or path.stat().st_size != size or digest(path) != sha:
                errors.append(f"Missing or modified asset: {relative}")
        except (ValueError, OSError) as exc:
            errors.append(f"{relative}: {exc}")
    return errors


def load_reviews(path: Path, documents: list[Document]) -> list[Review]:
    path = managed_path(path)
    reviews = TypeAdapter(list[Review]).validate_json(path.read_text()) if path.exists() else []
    assets = {
        (d.download.sha256, a.sha256)
        for d in documents
        for a in d.assets
        if a.kind in ("page_render", "card_candidate", "extracted_image")
    }
    seen: set[tuple[str, str]] = set()
    for review in reviews:
        key = review.source_sha256, review.asset_sha256
        if key not in assets:
            raise ValueError("Review refers to a missing source/visual asset hash")
        if key in seen:
            raise ValueError("Duplicate or conflicting review; edit the existing decision")
        seen.add(key)
    return reviews


def coverage_status(reviewed: int, document_count: int) -> str:
    if reviewed:
        return "reviewed_assets_available"
    return "unreviewed_sources_available" if document_count else "gap"


def coverage_row(state: str, manifest: Manifest, events: list[Event]) -> dict[str, Any]:
    documents = [d for d in manifest.documents if d.download.source.discovery_jurisdiction == state]
    ledger = [e for e in events if e.jurisdiction == state]
    kinds = Counter(a.kind for d in documents for a in d.assets)
    reviewed = sum(
        r.status == "accepted" and r.depicted_jurisdiction == state for r in manifest.reviews
    )
    return {
        "jurisdiction": state,
        "requested_this_run": state in manifest.requested_jurisdictions,
        "discovery_events_this_run": sum(e.stage == "discovery" for e in ledger),
        "fetch_failures_this_run": sum(e.stage == "fetch" and e.status == "failed" for e in ledger),
        "extraction_failures_this_run": sum(
            e.stage == "extract" and e.status == "failed" for e in ledger
        ),
        "source_documents": len(documents),
        "relevance_candidates": sum(d.relevance == "candidate" for d in documents),
        "quarantined_documents": sum(d.relevance == "quarantined" for d in documents),
        "native_images": kinds["extracted_image"],
        "rendered_pages": len(
            {
                (d.download.sha256, a.page_number)
                for d in documents
                for a in d.assets
                if a.kind == "page_render"
            }
        ),
        "rendered_plate_files": kinds["page_render"],
        "card_boundary_candidates": kinds["card_candidate"],
        "accepted_reference_assets": reviewed,
        "coverage_status": coverage_status(reviewed, len(documents)),
    }


def coverage(manifest: Manifest, events: list[Event]) -> list[dict[str, Any]]:
    """Exactly 51 state/DC rows; federal coverage is always reported separately."""
    return [coverage_row(state, manifest, events) for state in sorted(STATE_DOMAINS)]


def federal_coverage(manifest: Manifest, events: list[Event]) -> dict[str, Any]:
    return {**coverage_row(FEDERAL_CODE, manifest, events), "credential_format": "unclassified"}


def write_reports(root: Path, manifest: Manifest, events: list[Event]) -> None:
    root = managed_path(root)
    rows = coverage(manifest, events)
    atomic_json(root / "coverage.json", rows)
    federal = federal_coverage(manifest, events)
    atomic_json(root / "federal-coverage.json", federal)
    lines = [
        "# Reference library coverage",
        "",
        f"Run: `{manifest.run_id}`. Source revision: `{manifest.source_revision}`.",
        "",
        "Source counts are grouped by discovery jurisdiction. Only accepted, hash-bound human",
        "reviews establish depicted-state coverage. All other assets remain unreviewed.",
        "",
        "| State | PDFs | Native images | Plates | Crop proposals | Accepted assets | Status |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['jurisdiction']} | {row['source_documents']} | {row['native_images']} | "
            f"{row['rendered_pages']} | {row['card_boundary_candidates']} | "
            f"{row['accepted_reference_assets']} | {row['coverage_status']} |"
        )
    lines.extend(
        [
            "",
            "## Separate federal collection",
            "",
            f"US_FED: {federal['source_documents']} source documents; "
            f"{federal['coverage_status']}. Format remains unclassified; "
            "ID-1 normalization is disabled.",
        ]
    )
    (root / "coverage.md").write_text("\n".join(lines) + "\n")
    e = html.escape
    cards: list[str] = []
    for document in manifest.documents:
        d = document.download
        previews = [a for a in document.assets if a.kind == "card_candidate"]
        if not previews:
            previews = [a for a in document.assets if a.kind == "thumbnail"]
        for asset in previews:
            page = asset.page_number
            plate = next(
                (
                    a.path
                    for a in document.assets
                    if a.kind == "page_render" and a.page_number == page
                ),
                d.path,
            )
            cards.append(
                f'<article data-state="{e(d.source.discovery_jurisdiction)}">'
                f'<a href="{e(plate, quote=True)}"><img loading="lazy" '
                f'src="{e(asset.path, quote=True)}" '
                f'alt="Unreviewed candidate, page {page}"></a>'
                f"<h2>{e(d.source.discovery_jurisdiction)} · page {page}</h2>"
                f"<p>{e(asset.kind)} · unreviewed</p>"
                f'<p><a href="{e(d.final_url, quote=True)}">Official source</a> · '
                f'<a href="{e(d.path, quote=True)}">Retained PDF</a></p>'
                f"<details><summary>Evidence identifiers</summary><p>Source SHA-256: "
                f"{e(d.sha256)}</p><p>Asset SHA-256: {e(asset.sha256)}</p>"
                f"<p>Publisher: {e(d.publisher_host)}. Retrieved: {e(d.retrieved_at)}</p>"
                f"<p>Features: {e(', '.join(document.matched_features))}</p></details></article>"
            )
    codes = sorted(
        {*STATE_DOMAINS, *(d.download.source.discovery_jurisdiction for d in manifest.documents)}
    )
    states = "".join(f'<option value="{s}">{s}</option>' for s in codes)
    page_html = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>State and Federal ID Reference Library</title><style>
:root {{font-family: system-ui; color: #182735; background: #f4f6f7;}}
body {{margin: 0 auto; max-width: 1400px; padding: 24px;}}
h1 {{font-size: 2rem;}} h2 {{font-size: 1rem;}} a {{color: #07558c;}}
main {{display: grid; grid-template-columns: repeat(auto-fill,minmax(290px,1fr)); gap: 20px;}}
article {{background: white; padding: 18px; border: 1px solid #ccd5db; border-radius: 8px;}}
img {{width: 100%; height: 210px; object-fit: contain; background: #eef1f3;}}
details {{overflow-wrap: anywhere; font-size: .8rem;}} select {{padding: 8px; margin: 16px 0;}}
[hidden] {{display: none;}}
</style><header><h1>State and Federal ID Reference Library</h1>
<p>Public official sources · 50 states + DC and a separate federal collection</p>
<p>These are <strong>unreviewed proposals</strong>. Publisher location does not identify the
depicted credential. Source geometry does not establish physical accuracy;
mixed federal pages are not normalized to ID-1.</p>
<p><a href="coverage.md">51-state/DC coverage</a> ·
<a href="federal-coverage.json">Separate federal coverage</a> ·
<a href="manifest.json">Manifest</a></p>
<label>Discovery jurisdiction
<select id="state"><option value="">All</option>{states}</select></label>
</header><main>{"".join(cards)}</main><script>
document.querySelector('#state').addEventListener('change', (event) => {{
  for (const card of document.querySelectorAll('article')) {{
    card.hidden = Boolean(event.target.value && card.dataset.state !== event.target.value);
  }}
}});
</script></html>"""
    (root / "index.html").write_text(page_html)


def read_manifest(root: Path) -> Manifest:
    return Manifest.model_validate_json((root / "manifest.json").read_text())


def verify(root: Path) -> list[str]:
    manifest = read_manifest(root)
    errors = [error for d in manifest.documents for error in validate_document(d, root)]
    try:
        # Apply the same binding checks to the manifest's embedded review decisions.
        temp_assets = {
            (d.download.sha256, a.sha256)
            for d in manifest.documents
            for a in d.assets
            if a.kind in ("page_render", "card_candidate", "extracted_image")
        }
        if any((r.source_sha256, r.asset_sha256) not in temp_assets for r in manifest.reviews):
            errors.append("Manifest contains a review without a source/visual asset binding")
    except ValueError as exc:
        errors.append(str(exc))
    return errors
