"""Export citation metadata and reviewed geometry; never copy source media or prose."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

from state_id_harvester.catalog import export_catalog
from state_id_harvester.library import read_manifest
from state_id_harvester.publication_overlay import merge_overlay

JURISDICTIONS = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}


def citation(document: dict) -> dict:
    download = document["download"]
    url = download["final_url"]
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Public citations require credential-free HTTPS URLs")
    return {
        "title": " ".join((document.get("title") or "Official source document").split())[:240],
        "url": url,
        "sha256": download["sha256"],
        "retrieved_at": download["retrieved_at"],
        "publisher_host": download["publisher_host"],
        "publisher_jurisdiction": download.get("publisher_jurisdiction"),
        "discovery_jurisdiction": download["source"]["discovery_jurisdiction"],
        "relevance": document["relevance"],
        "review_status": document.get("review_status", "unreviewed"),
        "page_count": document["page_count"],
        "credential_format": download["source"].get("credential_format") or "ID1",
    }


def collection_row(code: str, name: str, manifest: dict, row: dict, cohorts: list[dict]) -> dict:
    documents = [
        d
        for d in manifest["documents"]
        if d["download"]["source"]["discovery_jurisdiction"] == code
    ]
    counts = {
        "sources": len(documents),
        "relevant_sources": sum(d["relevance"] == "candidate" for d in documents),
        "embedded_images": sum(
            a["kind"] == "extracted_image" for d in documents for a in d["assets"]
        ),
        "rendered_pages": sum(
            len({a["page_number"] for a in d["assets"] if a["kind"] == "page_render"})
            for d in documents
        ),
        "crop_candidates": sum(
            a["kind"] == "card_candidate" for d in documents for a in d["assets"]
        ),
        "accepted_cohorts": sum(c["jurisdiction"] == code for c in cohorts),
    }
    return {
        "code": code,
        "name": name,
        "status": "sources_available" if documents else "gap",
        "review_status": "reviewed" if counts["accepted_cohorts"] else "unreviewed",
        "counts": counts,
        "fetch_failures": row.get("fetch_failures_this_run", 0),
        "extraction_failures": row.get("extraction_failures_this_run", 0),
        "sources": [citation(d) for d in documents],
    }


def public_catalog(
    manifest: dict,
    coverage: list[dict],
    cohorts: list[dict],
    federal_manifest: dict | None = None,
    federal_coverage: dict | None = None,
) -> dict:
    """Allowlist output fields; federal collection never changes state/DC counts."""
    coverage_by_state = {row["jurisdiction"]: row for row in coverage}
    rows = [
        collection_row(code, name, manifest, coverage_by_state.get(code, {}), cohorts)
        for code, name in sorted(JURISDICTIONS.items())
    ]
    federal = collection_row(
        "US_FED",
        "United States federal",
        federal_manifest or {"documents": []},
        federal_coverage or {},
        [],
    )
    federal["credential_format"] = "unclassified"
    count_keys = rows[0]["counts"].keys()
    return {
        "schema_version": 1,
        "generated_at": manifest["generated_at"],
        "library_run_id": manifest["run_id"],
        "stats": {
            "jurisdictions": len(rows),
            "jurisdictions_with_sources": sum(bool(r["sources"]) for r in rows),
            "jurisdictions_with_accepted_cohorts": sum(
                bool(r["counts"]["accepted_cohorts"]) for r in rows
            ),
            **{key: sum(r["counts"][key] for r in rows) for key in count_keys},
        },
        "jurisdictions": rows,
        "federal": federal,
    }


def merge_publication_overlay(catalog: dict, overlay: object) -> dict:
    """Retain independently published source metadata across scheduled exports."""
    return merge_overlay(catalog, overlay, set(JURISDICTIONS))


def public_cohorts(cohorts: list[dict]) -> dict:
    """Reviewed geometry is public; freeform source callouts remain in the vault."""
    return {
        "schema_version": 1,
        "coordinate_convention": "unit square; nominal ID-1; no inferred metric accuracy",
        "routing": "candidate_set; barcode fields remain untrusted claims",
        "cohorts": [
            {
                **{
                    key: c[key]
                    for key in (
                        "cohort_id",
                        "jurisdiction",
                        "credential_type",
                        "orientation",
                        "iins",
                        "issue_date_start",
                        "issue_date_end",
                        "design_generation",
                        "review_status",
                    )
                },
                "source_sha256s": sorted({e["source_sha256"] for e in c["evidence"]}),
                "zones": [
                    {
                        key: z[key]
                        for key in ("name", "bbox_uv", "geometry_basis", "measured_error_mm")
                    }
                    for z in c["zones"]
                ],
            }
            for c in cohorts
        ],
    }


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def write_wireframes(directory: Path, cohorts: list[dict]) -> None:
    """Project reviewed rectangles only; no page resources or font glyphs are used."""
    directory.mkdir(parents=True, exist_ok=True)
    for previous in directory.glob("*.svg"):
        previous.unlink()
    for cohort in cohorts:
        width, height = (8560, 5398) if cohort["orientation"] == "horizontal" else (5398, 8560)
        svg = ET.Element(
            "svg",
            {
                "xmlns": "http://www.w3.org/2000/svg",
                "viewBox": f"0 0 {width} {height}",
                "data-cadastre-diagram": "reviewed-geometry",
                "fill": "none",
                "stroke": "currentColor",
                "stroke-width": "12",
            },
        )
        ET.SubElement(
            svg, "rect", {"x": "6", "y": "6", "width": str(width - 12), "height": str(height - 12)}
        )
        for zone in cohort["zones"]:
            x0, y0, x1, y1 = zone["bbox_uv"]
            ET.SubElement(
                svg,
                "rect",
                {
                    "x": f"{x0 * width:.4f}",
                    "y": f"{y0 * height:.4f}",
                    "width": f"{(x1 - x0) * width:.4f}",
                    "height": f"{(y1 - y0) * height:.4f}",
                },
            )
        (directory / f"{cohort['cohort_id']}.svg").write_text(
            ET.tostring(svg, encoding="unicode") + "\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("output"))
    parser.add_argument("--public", type=Path, default=Path("web/public"))
    parser.add_argument("--federal-source", type=Path, default=Path("output/federal"))
    parser.add_argument("--library", type=Path, default=Path("library"))
    parser.add_argument("--cohorts", type=Path, default=Path("cohorts.json"))
    parser.add_argument(
        "--publication-overlay",
        type=Path,
        default=Path("docs/source-research/publication-overlay.json"),
        help="Optional durable source and reference metadata overlay",
    )
    args = parser.parse_args()
    manifest_model = read_manifest(args.source)
    # Existing exporter verifies accepted reviews, matching hashes, pages and cohort identity.
    with tempfile.TemporaryDirectory() as temporary:
        checked = Path(temporary) / "checked.json"
        export_catalog(manifest_model, args.cohorts, checked)
        cohorts = json.loads(checked.read_text())["cohorts"]
    manifest = manifest_model.model_dump(mode="json")
    coverage = json.loads((args.source / "coverage.json").read_text())
    federal_manifest = None
    federal_coverage = None
    if (args.federal_source / "manifest.json").exists():
        federal_manifest = read_manifest(args.federal_source).model_dump(mode="json")
        federal_coverage = json.loads((args.federal_source / "federal-coverage.json").read_text())
    catalog = public_catalog(manifest, coverage, cohorts, federal_manifest, federal_coverage)
    if args.publication_overlay.exists():
        catalog = merge_publication_overlay(
            catalog, json.loads(args.publication_overlay.read_text())
        )
    write_json(args.public / "data/catalog.json", catalog)
    write_json(args.public / "data/cohorts.json", public_cohorts(cohorts))
    write_wireframes(args.public / "wireframes", cohorts)
    # Public searchable metadata uses exactly the same allowlist as the website.
    write_json(
        args.library / "manifest.json",
        {
            "schema_version": 1,
            "generated_at": catalog["generated_at"],
            "library_run_id": catalog["library_run_id"],
            "documents": [
                s for row in [*catalog["jurisdictions"], catalog["federal"]] for s in row["sources"]
            ],
        },
    )
    write_json(args.library / "coverage.json", catalog["jurisdictions"])
    write_json(args.library / "summary.json", catalog["stats"])
    write_json(args.library / "federal.json", catalog["federal"])
    lines = [
        "# Cadastre collection coverage",
        "",
        "Source collection and reviewed design coverage are separate.",
        "",
        "| Jurisdiction | Sources | Relevant candidates | Reviewed cohorts |",
        "| --- | ---: | ---: | ---: |",
    ]
    lines.extend(
        f"| {r['name']} ({r['code']}) | {r['counts']['sources']} | "
        f"{r['counts']['relevant_sources']} | {r['counts']['accepted_cohorts']} |"
        for r in catalog["jurisdictions"]
    )
    lines.extend(
        [
            "",
            "## Separate federal collection",
            "",
            f"US_FED: {catalog['federal']['counts']['sources']} sources; "
            f"{catalog['federal']['counts']['accepted_cohorts']} reviewed cohorts. "
            "Format unclassified; ID-1 normalization disabled.",
        ]
    )
    (args.library / "coverage.md").write_text("\n".join(lines) + "\n")
    for schema in Path("schemas").glob("*.schema.json"):
        destination = args.public / "schemas" / schema.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(schema, destination)
    print(json.dumps(catalog["stats"], sort_keys=True))


if __name__ == "__main__":
    main()
