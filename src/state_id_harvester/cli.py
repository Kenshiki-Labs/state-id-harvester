from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import os
import sys
from pathlib import Path

from .catalog import export_catalog
from .library import (
    coverage,
    publish_metadata,
    read_manifest,
    verify,
    write_reports,
)
from .models import Event, Options
from .pipeline import harvest
from .seeds import STATE_DOMAINS


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Build an auditable 51-jurisdiction ID reference library"
    )
    commands = result.add_subparsers(dest="command", required=True)
    run = commands.add_parser("harvest", help="Discover, fetch, extract, and report")
    selection = run.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true", help="All 50 states and DC")
    selection.add_argument("--states", nargs="+", choices=sorted(STATE_DOMAINS))
    run.add_argument("--output", type=Path, default=Path("output"))
    run.add_argument("--reviews", type=Path, default=Path("reviews.json"))
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
        help="Fail unless every requested state has a parsed source",
    )
    for command, help_text in (
        ("verify", "Rehash all manifest sources and assets"),
        ("report", "Regenerate the contact sheet and coverage"),
        ("publish-metadata", "Copy compact library metadata for git"),
        ("export-catalog", "Export reviewed topology/cohort interchange"),
    ):
        sub = commands.add_parser(command, help=help_text)
        sub.add_argument("--output", type=Path, default=Path("output"))
        if command == "publish-metadata":
            sub.add_argument("--destination", type=Path, default=Path("library"))
        if command == "export-catalog":
            sub.add_argument("--cohorts", type=Path, default=Path("cohorts.json"))
    return result


def main() -> None:
    args_list = sys.argv[1:]
    if args_list and args_list[0].startswith("--") and args_list[0] not in ("--help", "-h"):
        args_list = ["harvest", *args_list]
    args = parser().parse_args(args_list)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # Avoid logging HTTP request URLs with potentially sensitive provider query data.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        if args.command == "harvest":
            options = Options(
                refresh=args.refresh,
                workers=args.workers,
                dpi=args.dpi,
                max_pdfs_per_state=args.max_pdfs_per_state,
                crawl_pages=args.crawl_pages,
                max_render_pages=args.max_render_pages,
                max_pages=args.max_pages,
                max_pixels=args.max_pixels,
                detect_boundaries=not args.no_boundaries,
                ocr=args.ocr,
            )
            states = sorted(STATE_DOMAINS) if args.all else sorted(set(args.states))
            args.output.mkdir(parents=True, exist_ok=True)
            with (args.output / ".harvest.lock").open("w") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError("Another harvest owns this output directory") from None
                manifest = asyncio.run(harvest(states, args.output, options, args.reviews))
            rows = coverage(manifest, [])
            print("State  PDFs  Native  Plates  Crops  Accepted")
            for row in rows:
                if row["jurisdiction"] in states:
                    print(
                        f"{row['jurisdiction']:5} {row['source_documents']:4} "
                        f"{row['native_images']:7} {row['rendered_pages']:7} "
                        f"{row['card_boundary_candidates']:6} {row['accepted_reference_assets']:9}"
                    )
            if not manifest.documents or (
                args.fail_on_gap
                and any(
                    row["source_documents"] == 0 for row in rows if row["jurisdiction"] in states
                )
            ):
                raise ValueError(
                    "Harvest completed with source coverage gaps; inspect coverage and events"
                )
        elif args.command == "verify":
            errors = verify(args.output)
            if errors:
                raise ValueError("\n".join(errors))
            print("All retained manifest sources and assets match their SHA-256 and byte counts.")
        elif args.command == "report":
            manifest = read_manifest(args.output)
            events = [
                Event.model_validate(item)
                for item in json.loads((args.output / "events.json").read_text())
            ]
            write_reports(args.output, manifest, events)
        elif args.command == "publish-metadata":
            publish_metadata(args.output, args.destination)
        elif args.command == "export-catalog":
            export_catalog(
                read_manifest(args.output),
                args.cohorts,
                args.output / "pulse_state_catalog_v1.json",
            )
    except (ValueError, OSError) as exc:
        logging.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
