#!/usr/bin/env python3
"""Private, source-bound WA crop regression and native-overlay review packet.

Run against an existing private library; no source imagery is copied into the repo.
The fixed benchmark proves these documents only, not 51-jurisdiction accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
from pathlib import Path
from typing import Any

import pymupdf

from state_id_harvester.extract import fingerprint
from state_id_harvester.extraction_assets import AssetWriter
from state_id_harvester.extraction_objects import NativeObjectStreams
from state_id_harvester.extraction_pages import NativeImages
from state_id_harvester.models import Options
from state_id_harvester.pdf_components import component_groups
from state_id_harvester.pdf_objects import inventory_page
from state_id_harvester.topology import detect

WA = "d3027774492b8657bb4b712cb5f1218911a4b94602c342fc8a307a98525e4676"
PAY = "1a2f36f182e098ea00eeff86749f495279118792963f8bc4c56808c2af07aaa2"
ADMIN = "b98a94ca7ac7e8ba07f989fd156eb1a3bbf09c8d06537ab391700732baed0124"
BASELINE = "99e27ddb7cb495ef"
EXPECTED = {26, 30, 32, 34, 37, 39, 44, 128}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def baseline(root: Path, output: Path, sha: str, pages: set[int]) -> dict[str, Any]:
    folder = root / "WA/derived" / sha / BASELINE
    candidate_path = folder / "geometry/topology_candidates.json"
    candidates = json.loads(candidate_path.read_text())
    selected = [c for c in candidates if c["page_number"] in pages]
    for candidate in selected:
        source = root / candidate["crop_path"]
        dest = output / "before" / sha[:12] / source.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        candidate["review_asset"] = dest.relative_to(output).as_posix()
        candidate["review_asset_sha256"] = sha256(dest)
        pix = pymupdf.Pixmap(str(dest))
        candidate["review_dimensions_px"] = [pix.width, pix.height]
    geometry = json.loads((folder / "geometry/pages.json").read_text())
    images = [
        image for page in geometry if page["page_number"] in pages for image in page["images"]
    ]
    return {
        "extraction_fingerprint": BASELINE,
        "candidate_receipt_path": str(candidate_path),
        "candidate_receipt_sha256": sha256(candidate_path),
        "all_document_candidates": len(candidates),
        "selected_page_candidates": selected,
        "selected_page_preserved_image_xrefs": sorted({image["xref"] for image in images}),
    }


def inspect_page(
    doc: Any,
    number: int,
    sha: str,
    output: Path,
    writer: AssetWriter,
    images: NativeImages,
    context: str,
    streams: NativeObjectStreams,
) -> dict[str, Any]:
    page = doc[number - 1]
    inv = inventory_page(page, source_sha256=sha, page_number=number)
    groups = component_groups(inv, max_image_pixels=40_000_000, document_native_text=context)
    preserved = images.read(page, number)
    source_streams = streams.preserve(inv)
    proposals = []
    for candidate, encoded in detect(page, [], number, inventory=inv, groups=groups):
        name = f"after/{sha[:12]}/{candidate.candidate_id}.{candidate.crop_format}"
        path = writer.save(name, encoded, "card_candidate", number)
        record = candidate.model_copy(update={"crop_path": path}).model_dump(mode="json")
        record["review_asset_sha256"] = hashlib.sha256(encoded).hexdigest()
        proposals.append(record)
    native_path = output / "inventory" / sha[:12] / f"p{number}.json"
    write_json(native_path, inv.model_dump(mode="json"))
    page_path = output / "pages" / sha[:12] / f"p{number}-review-120dpi.png"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page.get_pixmap(dpi=120, alpha=False).save(page_path)
    return {
        "page_number": number,
        "inventory_path": native_path.relative_to(output).as_posix(),
        "inventory_sha256": sha256(native_path),
        "page_preview_path": page_path.relative_to(output).as_posix(),
        "page_preview_sha256": sha256(page_path),
        "page_preview_purpose": "120dpi raster page review only; not native image or metric master",
        "preserved_native_images": [image.model_dump(mode="json") for image in preserved],
        "preserved_native_content_forms_fonts": source_streams,
        "native_component_groups": [group.model_dump(mode="json") for group in groups],
        "proposals": proposals,
    }


def inspect_source(root: Path, output: Path, sha: str, numbers: list[int]) -> dict[str, Any]:
    source = root / "WA/raw_pdfs" / f"{sha}.pdf"
    if sha256(source) != sha:
        raise ValueError("Retained source SHA-256 mismatch")
    receipt = json.loads((root / "WA/derived" / sha / BASELINE / "document.json").read_text())
    object_folder = Path("source_objects") / sha[:12]
    writer = AssetWriter(output / object_folder, object_folder, 300_000_000)
    warnings: list[str] = []
    with pymupdf.open(source) as doc:
        images = NativeImages(doc, Options(), writer, warnings)
        streams = NativeObjectStreams(doc, writer)
        context = "\n".join(page.get_text() for page in doc)
        pages = [
            inspect_page(doc, n, sha, output, writer, images, context, streams) for n in numbers
        ]
    return {
        "source_path": str(source),
        "source_sha256": sha,
        "download": receipt["download"],
        "title": receipt["title"],
        "baseline": baseline(root, output, sha, set(numbers)),
        "pages": pages,
        "warnings": warnings,
        "native_asset_receipts": [asset.model_dump(mode="json") for asset in writer.assets],
        "source_unchanged_after": sha256(source) == sha,
    }


def verify(results: list[dict[str, Any]]) -> dict[str, Any]:
    guide, pay, admin = results
    candidates = [candidate for page in guide["pages"] for candidate in page["proposals"]]
    xrefs = {candidate["native_provenance"]["xref"] for candidate in candidates}
    if xrefs != EXPECTED or len(candidates) != 8:
        raise AssertionError(f"WA native proposal benchmark changed: {sorted(xrefs)}")
    for source in (pay, admin):
        if any(page["proposals"] for page in source["pages"]):
            raise AssertionError("Administrative document emitted a credential proposal")
    before = set(guide["baseline"]["selected_page_preserved_image_xrefs"])
    recovered = sorted(EXPECTED - before)
    if recovered != [30, 34, 39, 44, 128]:
        raise AssertionError(f"Unexpected baseline preservation difference: {recovered}")
    return {
        "status": "passed",
        "scope": "WA fixed three-source benchmark only",
        "guide_pages": [11, 12, 13, 14],
        "native_reference_proposals": 8,
        "native_reference_xrefs": sorted(xrefs),
        "recovered_native_card_image_xrefs": recovered,
        "baseline_native_reference_images_preserved": len(EXPECTED & before),
        "baseline_administrative_false_proposals": sum(
            source["baseline"]["all_document_candidates"] for source in (pay, admin)
        ),
        "after_administrative_proposals": 0,
        "temporary_xref43_proposals": 0,
        "raster_resampling": "none; original encoded image bytes",
        "accepted_cohorts": 0,
        "perimeter_accuracy": "unreviewed native image extents; no physical boundary claim",
        "annotation_policy": "No erasure; flattened annotations remain in original images",
    }


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def source_html(source: dict[str, Any]) -> str:
    result = [
        f"<section><h2>{esc(source['title'])}</h2>",
        f'<p><a href="{esc(source["download"]["final_url"])}">Official source</a> · '
        f"<code>{esc(source['source_sha256'])}</code></p>",
    ]
    for page in source["pages"]:
        number = page["page_number"]
        result.append(
            f'<h3>PDF page {number}</h3><p><a href="{esc(page["page_preview_path"])}">'
            "Whole page: 120 dpi review preview</a> · "
            f'<a href="{esc(page["inventory_path"])}">Native inventory</a></p>'
        )
        result.append('<div class="columns"><div><h4>Before: page-render crops</h4>')
        previous = source["baseline"]["selected_page_candidates"]
        for old in [candidate for candidate in previous if candidate["page_number"] == number]:
            result.append(
                f'<figure><img src="{esc(old["review_asset"])}" alt="Previous crop proposal">'
                f"<figcaption>{esc(old['candidate_id'])} · {esc(old['method'])} · "
                f"{esc(old['review_dimensions_px'])} px · raster derivative</figcaption></figure>"
            )
        result.append("</div><div><h4>After: original image components</h4>")
        for candidate in page["proposals"]:
            native = candidate["native_provenance"]
            dimensions = native["source_dimensions_px"]
            result.append(
                f'<figure><img src="{esc(candidate["crop_path"])}" '
                f'width="{dimensions[0]}" alt="Unreviewed original image component">'
                f"<figcaption>xref {native['xref']} · {dimensions[0]}×{dimensions[1]} native px"
                f" · PPI at PDF placement {esc(native['effective_ppi_at_pdf_placement'])}"
                "<br>No resampling; image extent, not accepted perimeter. "
                "Baked annotations remain.</figcaption></figure>"
            )
        if not page["proposals"]:
            result.append(
                '<p class="pass">Abstained. Source, images, native text and vectors retained.</p>'
            )
        result.append("</div></div>")
    return "".join(result) + "</section>"


def contact_sheet(output: Path, results: list[dict[str, Any]], metrics: dict[str, Any]) -> None:
    content = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width">
<title>WA native PDF extraction — private review</title><style>
body{font:15px/1.5 system-ui,sans-serif;margin:32px;color:#202528;background:#f7f8f6}
main{max-width:1400px;margin:auto}
h1{font-size:38px;letter-spacing:-1.5px}h2{margin-top:64px}code{overflow-wrap:anywhere;font-size:12px}
.columns{display:grid;grid-template-columns:1fr 1fr;gap:28px}
.columns>div{min-width:0;background:white;padding:20px;border:1px solid #d5ddda}
figure{margin:0 0 28px}
img{display:block;max-width:100%;height:auto}
figcaption{font-size:12px;overflow-wrap:anywhere;margin-top:8px}
.pass{color:#185b46}a{color:#175e54}pre{white-space:pre-wrap}@media(max-width:750px){.columns{grid-template-columns:1fr}body{margin:16px}}
</style><main>
<p>CADASTRE / PRIVATE SOURCE REVIEW / ZERO ACCEPTED COHORTS</p>
<h1>Original components. Honest resolution.</h1>
<p>The five omitted Washington native card images are recovered. 
The eight image extents are unreviewed reference proposals.
The TOUCH/LOOK/ASK panel and letter-size temporary specimen are not card proposals. 
Six administrative false proposals now abstain.
No annotation pixels have been removed. 
Original native image bytes are displayed without enlargement.</p>"""
    content += "<pre>" + esc(json.dumps(metrics, indent=2)) + "</pre>"
    content += "".join(source_html(source) for source in results)
    (output / "index.html").write_text(content + "</main></html>")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = [inspect_source(args.library_root, output, WA, [11, 12, 13, 14])]
    for sha in (PAY, ADMIN):
        with pymupdf.open(args.library_root / "WA/raw_pdfs" / f"{sha}.pdf") as doc:
            numbers = list(range(1, len(doc) + 1))
        results.append(inspect_source(args.library_root, output, sha, numbers))
    metrics = verify(results)
    write_json(
        output / "manifest.json",
        {
            "benchmark_version": 1,
            "implementation_fingerprint": fingerprint(Options()),
            "metrics": metrics,
            "sources": results,
        },
    )
    contact_sheet(output, results, metrics)
    print(
        json.dumps(
            {
                "manifest": str(output / "manifest.json"),
                "contact_sheet": str(output / "index.html"),
                "metrics": metrics,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
