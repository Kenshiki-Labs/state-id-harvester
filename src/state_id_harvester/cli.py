from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import os
import sys

from .catalog import export_catalog
from .library import coverage, federal_coverage, read_manifest, verify, write_reports
from .models import Event, Manifest, Options
from .paths import managed_path
from .pipeline import harvest
from .seeds import FEDERAL_CODE, STATE_DOMAINS


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Build auditable state and separately scoped federal ID reference collections"
    )
    commands = result.add_subparsers(dest="command", required=True)
    run = commands.add_parser("harvest", help="Discover, fetch, extract, and report")
    selection = run.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true", help="All 50 states and DC")
    selection.add_argument("--states", nargs="+", choices=sorted(STATE_DOMAINS))
    selection.add_argument(
        "--federal", action="store_true", help="Separate US_FED collection; no ID-1 normalization"
    )
    run.add_argument("--output", type=managed_path)
    run.add_argument("--reviews", type=managed_path)
    run.add_argument(
        "--refresh", action="store_true", help="Refetch sources; unchanged bytes reuse extraction"
    )
    run.add_argument("--workers", type=int, default=min(2, os.cpu_count() or 1))
    run.add_argument("--dpi", type=int, default=600)
    run.add_argument("--max-pdfs-per-state", type=int, default=8)
    run.add_argument("--crawl-pages", type=int, default=6)
    run.add_argument("--max-render-pages", type=int, default=12)
    run.add_argument("--max-pages", type=int, default=250)
    run.add_argument("--max-pixels", type=int, default=40_000_000)
    run.add_argument("--no-boundaries", action="store_true")
    run.add_argument("--ocr", action="store_true", help="Local tesseract OCR on ranked image pages")
    run.add_argument(
        "--fail-on-gap",
        action="store_true",
        help="Fail unless each requested collection has a parsed source",
    )
    images = commands.add_parser(
        "harvest-images", help="Independent private HTML gallery originals"
    )
    image_selection = images.add_mutually_exclusive_group()
    image_selection.add_argument("--all", action="store_true", help="All supplied gallery leads")
    image_selection.add_argument(
        "--states", nargs="+", choices=sorted([*STATE_DOMAINS, FEDERAL_CODE])
    )
    images.add_argument("--output", type=managed_path, default="output/gallery")
    images.add_argument("--import-manifest", type=managed_path, action="append", default=[])
    images.add_argument("--max-pages", type=int, default=40)
    images.add_argument("--max-assets", type=int, default=200)
    images.add_argument("--max-pixels", type=int, default=20_000_000)
    images.add_argument("--max-total-bytes", type=int, default=256_000_000)
    images.add_argument("--concurrency", type=int, default=2)
    for command, help_text in (
        ("verify", "Rehash all manifest sources and assets"),
        ("verify-images", "Verify private gallery originals and HTML evidence bindings"),
        ("report", "Regenerate the private contact sheet and coverage"),
        ("export-catalog", "Export reviewed state topology/cohort interchange"),
    ):
        sub = commands.add_parser(command, help=help_text)
        sub.add_argument(
            "--output",
            type=managed_path,
            default="output/gallery" if command == "verify-images" else "output",
        )
        if command == "export-catalog":
            sub.add_argument("--cohorts", type=managed_path, default="cohorts.json")
    return result


def harvest_options(args: argparse.Namespace) -> Options:
    return Options(
        refresh=args.refresh,
        workers=args.workers,
        dpi=args.dpi,
        max_pdfs_per_state=args.max_pdfs_per_state,
        crawl_pages=args.crawl_pages,
        max_render_pages=args.max_render_pages,
        max_pages=args.max_pages,
        max_pixels=args.max_pixels,
        detect_boundaries=not (args.no_boundaries or args.federal),
        ocr=args.ocr,
    )


def selected_collections(args: argparse.Namespace) -> list[str]:
    if args.federal:
        return [FEDERAL_CODE]
    return sorted(STATE_DOMAINS) if args.all else sorted(set(args.states))


def locked_harvest(args: argparse.Namespace, states: list[str], options: Options) -> Manifest:
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / ".harvest.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another harvest owns this output directory") from None
        return asyncio.run(harvest(states, args.output, options, args.reviews))


def resolve_harvest_paths(args: argparse.Namespace) -> None:
    args.output = managed_path(args.output or ("output/federal" if args.federal else "output"))
    if args.federal and args.output == managed_path("output"):
        raise ValueError("Federal collection requires a separate output directory")
    default_reviews = args.output / "reviews.json" if args.federal else "reviews.json"
    args.reviews = managed_path(args.reviews or default_reviews)


def run_harvest(args: argparse.Namespace) -> None:
    states = selected_collections(args)
    resolve_harvest_paths(args)
    manifest = locked_harvest(args, states, harvest_options(args))
    rows = [federal_coverage(manifest, [])] if args.federal else coverage(manifest, [])
    requested = [row for row in rows if row["jurisdiction"] in states]
    print("Collection  PDFs  Native  Plates  Crops  Accepted")
    for row in requested:
        print(
            f"{row['jurisdiction']:10} {row['source_documents']:4} "
            f"{row['native_images']:7} {row['rendered_pages']:7} "
            f"{row['card_boundary_candidates']:6} {row['accepted_reference_assets']:9}"
        )
    if not manifest.documents or (
        args.fail_on_gap and any(r["source_documents"] == 0 for r in requested)
    ):
        raise ValueError("Harvest completed with source coverage gaps; inspect coverage and events")


def run_verify(args: argparse.Namespace) -> None:
    errors = verify(args.output)
    if errors:
        raise ValueError("\n".join(errors))
    print("All retained manifest sources and assets match their SHA-256 and byte counts.")


def run_report(args: argparse.Namespace) -> None:
    events = [
        Event.model_validate(item) for item in json.loads((args.output / "events.json").read_text())
    ]
    write_reports(args.output, read_manifest(args.output), events)


def run_export(args: argparse.Namespace) -> None:
    export_catalog(
        read_manifest(args.output), args.cohorts, args.output / "pulse_state_catalog_v1.json"
    )


def run_gallery(args: argparse.Namespace) -> None:
    from .gallery import GalleryOptions, harvest_images
    from .gallery_seeds import HTML_GALLERY_SEEDS

    collections = sorted(HTML_GALLERY_SEEDS) if args.all else sorted(set(args.states or []))
    if not collections and not args.import_manifest:
        raise ValueError("Choose --all, --states, or --import-manifest for gallery harvest")
    output = managed_path(args.output)
    if (
        output == managed_path("output")
        or (output / "manifest.json").exists()
        and json.loads((output / "manifest.json").read_text()).get("track") != "html_gallery"
    ):
        raise ValueError("Gallery requires a separate private output directory")
    options = GalleryOptions(
        max_pages=args.max_pages,
        max_assets=args.max_assets,
        max_pixels=args.max_pixels,
        max_total_bytes=args.max_total_bytes,
        concurrency=args.concurrency,
    )
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".gallery.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = asyncio.run(harvest_images(collections, output, options, args.import_manifest))
    print(
        f"Gallery originals: {len(manifest['assets'])}; aliases: {len(manifest['aliases'])}; "
        f"events: {len(manifest['events'])}; accepted cohorts: 0"
    )


def run_verify_images(args: argparse.Namespace) -> None:
    from .gallery_verify import verify_gallery

    errors = verify_gallery(args.output)
    if errors:
        raise ValueError("Gallery verification failed: " + ", ".join(errors[:20]))
    print("All gallery originals, parent HTML, dimensions, and source bindings verify.")


def main() -> None:
    args_list = sys.argv[1:]
    if args_list and args_list[0].startswith("--") and args_list[0] not in ("--help", "-h"):
        args_list = ["harvest", *args_list]
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        args = parser().parse_args(args_list)
        handlers = {
            "harvest": run_harvest,
            "harvest-images": run_gallery,
            "verify": run_verify,
            "verify-images": run_verify_images,
            "report": run_report,
            "export-catalog": run_export,
        }
        handlers[args.command](args)
    except (ValueError, OSError):
        logging.exception("Reference collection command failed")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
