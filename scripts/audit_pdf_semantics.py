"""Build a private native-object/context benchmark; never a public specimen export."""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib
import json
from pathlib import Path

import pymupdf

from state_id_harvester.document_semantics import PageSemantics, analyze_document, audit_counts
from state_id_harvester.models import TextBlock
from state_id_harvester.paths import contained_path, managed_path
from state_id_harvester.semantic_review import (
    GroundedClaim,
    SemanticReviewProposal,
    review_request,
    validate_review,
)


def json_file(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def export_inspection_assets(
    source: Path, destination: Path, pages: list[PageSemantics]
) -> dict[str, str]:
    assets: dict[str, str] = {}
    with pymupdf.open(source) as document:
        for semantic_page in pages:
            number = semantic_page.page_number
            page = document[number - 1]
            page.get_pixmap(matrix=pymupdf.Matrix(1.4, 1.4), alpha=False).save(
                contained_path(destination, f"page-{number}.png")
            )
            for image in semantic_page.image_contexts:
                if image.xref == 0:
                    continue
                extracted = document.extract_image(image.xref)
                name = f"{image.image_id}.{extracted['ext']}"
                contained_path(destination, name).write_bytes(extracted["image"])
                assets[image.image_id] = name
                if image.mask_xref:
                    contained_path(destination, f"{image.image_id}-mask.stream").write_bytes(
                        document.xref_stream_raw(image.mask_xref)
                    )
    return assets


def observation_html(page: PageSemantics, identifiers: list[str]) -> str:
    rows = []
    for observation in page.observations:
        if observation.observation_id not in identifiers:
            continue
        citations = ", ".join(observation.span_ids)
        rows.append(
            f"<li><b>{html.escape(observation.kind)}</b> "
            f"<code>{html.escape(observation.observation_id)}</code>"
            f"<pre>{html.escape(observation.verbatim_text)}</pre>"
            f"<small>Native source bbox: {observation.source_bbox}; spans: {html.escape(citations)}"
            " · source statement, no executable rule</small></li>"
        )
    return "<ol>" + "".join(rows) + "</ol>"


def image_html(page: PageSemantics, image_id: str, assets: dict[str, str]) -> str:
    image = next(item for item in page.image_contexts if item.image_id == image_id)
    section = next((s for s in page.sections if s.section_id == image.section_id), None)
    heading = section.heading_verbatim if section else "Unscoped / ambiguous"
    preview = (
        f'<img src="{html.escape(assets[image_id], quote=True)}" alt="Unmodified native PDF image">'
        if image_id in assets
        else "Inline image: original PDF required"
    )
    return (
        f"<article><h3>{html.escape(image_id)}</h3>{preview}"
        f"<p>Native pixels: {image.width_px} × {image.height_px}. PDF xref {image.xref}, "
        f"mask {image.mask_xref}; paint sequence {image.paint_sequence_numbers}.</p>"
        f"<p>Native object refs: {html.escape(', '.join(image.native_object_refs))}; "
        f"placement {html.escape(image.native_placement_id or 'inventory not joined')}; "
        f"paint IDs {html.escape(', '.join(image.native_paint_ids))}. "
        f"Source stream SHA-256: <code>{image.source_stream_sha256}</code>.</p>"
        f"<p>Source placement: {image.placement_bbox}. No ID-1 geometry inferred.</p>"
        f"<h4>Native section context</h4><pre>{html.escape(heading)}</pre>"
        f"<p>{image.association_status} / {image.association_confidence}; "
        "specific leader endpoints unresolved; cross-source pairing pending.</p>"
        f"{observation_html(page, image.observation_ids)}</article>"
    )


def review_html(claims: list[GroundedClaim]) -> str:
    if not claims:
        return "<p>No semantic review proposal supplied. Layout observations remain unreviewed.</p>"
    rows = []
    for claim in claims:
        rows.append(
            f"<article><h3>{html.escape(claim.claim.claim_id)}</h3>"
            f"<p>{html.escape(claim.claim.rationale)}</p>"
            f"<pre>{html.escape(claim.model_dump_json(indent=2))}</pre></article>"
        )
    return (
        "<p>Quote, source identity and section binding checked. Interpretation remains unverified; "
        "no geometry transfer or runtime rule is authorized.</p><div class=cards>"
        + "".join(rows)
        + "</div>"
    )


def report_html(
    pages: list[PageSemantics],
    assets: dict[str, str],
    baseline: dict,
    claims: list[GroundedClaim],
) -> str:
    sections = []
    for page in pages:
        cards = "".join(image_html(page, image.image_id, assets) for image in page.image_contexts)
        sections.append(
            f"<section><h2>PDF page {page.page_number}</h2>"
            "<details><summary>Composed source page</summary>"
            f'<img class="plate" src="page-{page.page_number}.png" '
            'alt="Original page rendered for inspection">'
            f"</details><div class=cards>{cards}</div></section>"
        )
    checksum = pages[0].source_sha256
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        "<title>Private PDF semantics benchmark</title>"
        '<meta name="viewport" content="width=device-width"><style>'
        "body{font:16px system-ui;margin:2rem;color:#18232b;background:#f4f6f8}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere}"
        "article{background:white;padding:1.2rem;border:1px solid #ccd3da}"
        ".cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1rem}"
        "img{max-width:100%;height:auto}.plate{max-width:900px}small,code{overflow-wrap:anywhere}"
        "li{margin-bottom:1.2rem}</style><h1>Private native-source context audit</h1>"
        "<p>Unchanged PDF rasters and native text evidence. Rendering is for inspection; "
        "OCR is secondary. These are source observations, not runtime authenticity rules "
        "or calibrated field zones.</p>"
        f"<p>Source SHA-256: <code>{checksum}</code></p>"
        "<h2>Before</h2><p>Existing output observations and limitations:</p>"
        f"<pre>{html.escape(json.dumps(baseline, indent=2))}</pre>"
        "<h2>After</h2><p>Each source image placement keeps its own typographic section "
        "and cited statements. Old-design numbered rules never transfer to a neighboring "
        "version merely because it shares a page.</p>"
        + "".join(sections)
        + "<h2>Grounded review proposal</h2>"
        + review_html(claims)
        + "</html>"
    )


def load_inventories(source: Path, numbers: list[int], path: Path | None, native: bool) -> list:
    if path:
        return json.loads(path.read_text())
    if not native:
        return []
    # The inventory module is supplied by the native-object extraction component.
    module = importlib.import_module("state_id_harvester.pdf_objects")
    with source.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    with pymupdf.open(source) as document:
        return [
            module.inventory_page(
                document[number - 1], source_sha256=checksum, page_number=number
            ).model_dump(mode="json")
            for number in numbers
        ]


def check_expected_figure(page: PageSemantics, label: dict) -> dict:
    images = [image for image in page.image_contexts if image.xref == label["xref"]]
    if len(images) != 1:
        raise ValueError("Benchmark xref is missing or has multiple placements on this page")
    image = images[0]
    section = next((s for s in page.sections if s.section_id == image.section_id), None)
    heading_match = section is not None and label["heading_contains"] in section.heading_verbatim
    count = sum(
        observation.kind == "numbered_callout"
        for observation in page.observations
        if observation.observation_id in image.observation_ids
    )
    return {
        "page": label["page"],
        "xref": label["xref"],
        "heading_matched": heading_match,
        "expected_numbered_callouts": label["numbered_callouts"],
        "actual_numbered_callouts": count,
        "native_placement_id": image.native_placement_id,
        "passed": heading_match and count == label["numbered_callouts"],
    }


def evaluate_expectations(pages: list[PageSemantics], expected: dict) -> dict:
    """Compare operator-authored source labels; this is not an accuracy estimate."""
    if not expected.get("expected"):
        raise ValueError("Benchmark requires explicit source inspection labels")
    if any(page.source_sha256 != expected["source_sha256"] for page in pages):
        raise ValueError("Benchmark label source hash does not match")
    by_number = {page.page_number: page for page in pages}
    checks = [
        check_expected_figure(by_number[label["page"]], label) for label in expected["expected"]
    ]
    return {
        "source_sha256": expected["source_sha256"],
        "label_origin": expected["label_origin"],
        "evaluation_scope": "bounded source-layout benchmark; no generalization accuracy claim",
        "figures_expected": len(checks),
        "figures_matched": sum(c["passed"] for c in checks),
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=managed_path)
    parser.add_argument("destination", type=managed_path)
    parser.add_argument("--pages", nargs="+", type=int, default=[11, 12, 13, 14])
    parser.add_argument("--baseline-text", type=managed_path)
    parser.add_argument("--baseline-summary", type=managed_path)
    parser.add_argument("--review", type=managed_path)
    parser.add_argument(
        "--expectations",
        type=managed_path,
        help="Optional source-inspection labels for a bounded benchmark receipt",
    )
    parser.add_argument("--native-inventory", type=managed_path)
    parser.add_argument(
        "--native-objects",
        action="store_true",
        help="Build native object inventory using the installed pdf_objects module",
    )
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    raw_blocks = json.loads(args.baseline_text.read_text()) if args.baseline_text else []
    ocr = {
        number: [
            TextBlock.model_validate_json(json.dumps(row))
            for row in raw_blocks
            if row["page_number"] == number and row["method"] == "local_ocr"
        ]
        for number in args.pages
    }
    inventories = load_inventories(
        args.source, args.pages, args.native_inventory, args.native_objects
    )
    pages = analyze_document(
        args.source, args.pages, ocr, {record["page_number"]: record for record in inventories}
    )
    baseline = (
        json.loads(args.baseline_summary.read_text())
        if args.baseline_summary
        else {"provided": False}
    )
    assets = export_inspection_assets(args.source, args.destination, pages)
    json_file(
        contained_path(args.destination, "after.json"),
        [page.model_dump(mode="json") for page in pages],
    )
    json_file(contained_path(args.destination, "audit-counts.json"), audit_counts(pages))
    json_file(
        contained_path(args.destination, "review-requests.json"),
        [review_request(page).model_dump(mode="json") for page in pages],
    )
    claims = []
    if args.review:
        proposal = SemanticReviewProposal.model_validate_json(args.review.read_text())
        page = next(page for page in pages if page.page_number == proposal.page_number)
        claims = validate_review(page, proposal)
        json_file(
            contained_path(args.destination, "grounded-review.json"),
            [claim.model_dump(mode="json") for claim in claims],
        )
    contained_path(args.destination, "index.html").write_text(
        report_html(pages, assets, baseline, claims)
    )
    if args.expectations:
        json_file(
            contained_path(args.destination, "benchmark-results.json"),
            evaluate_expectations(pages, json.loads(args.expectations.read_text())),
        )
    print(json.dumps(audit_counts(pages), sort_keys=True))


if __name__ == "__main__":
    main()
