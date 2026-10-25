"""Resumable coordinator; only the parent process mutates run-level manifests."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import multiprocessing
import subprocess
import uuid
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import httpx

from .discovery import discover_all
from .extract import extract, fingerprint
from .library import load_reviews, validate_document, write_reports
from .models import Document, Download, Event, Manifest, Options, Source
from .network import USER_AGENT, Transport
from .storage import atomic_json, digest, now, within

LOG = logging.getLogger(__name__)


def revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")
    except (subprocess.CalledProcessError, OSError):
        return "uncommitted"


async def harvest(
    states: list[str],
    root: Path,
    options: Options,
    reviews_path: Path,
) -> Manifest:
    root = await asyncio.to_thread(root.resolve)
    root.mkdir(parents=True, exist_ok=True)
    run_id = now().replace(":", "").replace("+0000", "Z") + "-" + uuid.uuid4().hex[:8]
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True)
    events: list[Event] = []
    downloaded: list[Download] = []

    def event(source: Source, stage: str, status: str, detail: str) -> None:
        record = Event.model_validate(
            {
                "at": now(),
                "jurisdiction": source.discovery_jurisdiction,
                "url": source.url,
                "stage": stage,
                "status": status,
                "detail": detail,
            }
        )
        events.append(record)
        LOG.info("%s %s %s: %s", record.jurisdiction, stage, status, detail)

    async with httpx.AsyncClient(
        http2=True,
        timeout=20.0,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        limits=httpx.Limits(max_connections=15, max_keepalive_connections=15),
    ) as client:
        transport = Transport(client)
        candidates, discovery_events = await discover_all(states, transport, options.crawl_pages)
        events.extend(discovery_events)
        # Curated leads first; stable order for all remaining candidates.
        candidates.sort(
            key=lambda s: (s.discovery_jurisdiction, s.discovered_via != "curated_seed", s.url)
        )
        counts: dict[str, int] = {}
        selected: list[Source] = []
        for source in candidates:
            state = source.discovery_jurisdiction
            counts[state] = counts.get(state, 0) + 1
            if counts[state] <= options.max_pdfs_per_state:
                selected.append(source)
            else:
                event(source, "fetch", "skipped", "Per-jurisdiction candidate download budget")
        atomic_json(run_dir / "candidates.json", [s.model_dump(mode="json") for s in candidates])
        fetch_slots = asyncio.Semaphore(15)

        async def fetch_one(source: Source) -> None:
            async with fetch_slots:
                key = hashlib.sha256(
                    (source.discovery_jurisdiction + source.url).encode()
                ).hexdigest()
                receipt = root / "cache" / "downloads" / f"{key}.json"
                try:
                    if receipt.exists() and not options.refresh:
                        cached = Download.model_validate_json(receipt.read_text())
                        path = within(root, cached.path)
                        if (
                            path.is_file()
                            and path.stat().st_size == cached.size_bytes
                            and digest(path) == cached.sha256
                        ):
                            downloaded.append(cached)
                            event(source, "fetch", "cached", cached.sha256)
                            return
                    result = await transport.download(source, root, options)
                    downloaded.append(result)
                    atomic_json(receipt, result.model_dump(mode="json"))
                    event(source, "fetch", "ok", f"{result.size_bytes} bytes; {result.sha256}")
                except Exception as exc:
                    event(source, "fetch", "failed", f"{type(exc).__name__}: {exc}")

        await asyncio.gather(*(fetch_one(source) for source in selected))

    previous: list[Document] = []
    if (root / "manifest.json").exists():
        previous = Manifest.model_validate_json((root / "manifest.json").read_text()).documents
    documents: dict[tuple[str, str], Document] = {
        (d.download.source.discovery_jurisdiction, d.download.sha256): d for d in previous
    }
    loop = asyncio.get_running_loop()
    extraction_slots = asyncio.Semaphore(options.workers)
    with ProcessPoolExecutor(
        max_workers=options.workers, mp_context=multiprocessing.get_context("spawn")
    ) as pool:

        async def extract_one(download: Download) -> None:
            async with extraction_slots:
                state = download.source.discovery_jurisdiction
                receipt = (
                    root
                    / state
                    / "derived"
                    / download.sha256
                    / fingerprint(options)
                    / "document.json"
                )
                try:
                    if receipt.exists():
                        cached = Document.model_validate_json(receipt.read_text())
                        if not validate_document(cached, root):
                            result = cached.model_copy(update={"download": download})
                            documents[(state, download.sha256)] = result
                            event(download.source, "extract", "cached", download.sha256)
                            return
                    result = await loop.run_in_executor(pool, extract, download, str(root), options)
                    documents[(state, download.sha256)] = result
                    event(
                        download.source,
                        "extract",
                        "ok",
                        f"{result.page_count} pages; {len(result.assets)} assets; "
                        f"{result.relevance}",
                    )
                except Exception as exc:
                    event(download.source, "extract", "failed", f"{type(exc).__name__}: {exc}")

        # Deduplicate aliases of the same PDF within a jurisdiction before scheduling workers.
        unique_downloads = {(d.source.discovery_jurisdiction, d.sha256): d for d in downloaded}
        await asyncio.gather(*(extract_one(d) for d in unique_downloads.values()))
    ordered = sorted(
        documents.values(),
        key=lambda d: (d.download.source.discovery_jurisdiction, d.download.sha256),
    )
    manifest = Manifest(
        generated_at=now(),
        run_id=run_id,
        source_revision=revision(),
        requested_jurisdictions=states,
        options=options,
        documents=ordered,
        reviews=load_reviews(reviews_path, ordered),
    )
    ledger = [e.model_dump(mode="json") for e in events]
    atomic_json(run_dir / "events.json", ledger)
    atomic_json(run_dir / "manifest.json", manifest.model_dump(mode="json"))
    atomic_json(root / "events.json", ledger)
    atomic_json(root / "manifest.json", manifest.model_dump(mode="json"))
    write_reports(root, manifest, events)
    # Retained raw PDFs may have failed parsing/size/page budgets; include them in audit inventory.
    atomic_json(root / "downloads.json", [d.model_dump(mode="json") for d in downloaded])
    return manifest
