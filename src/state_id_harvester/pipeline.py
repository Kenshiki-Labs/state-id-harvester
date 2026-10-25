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


MANIFEST_FILENAME = "manifest.json"


class HarvestRun:
    """A single writer owns download receipts, extraction receipts and the run ledger."""

    def __init__(self, states: list[str], root: Path, options: Options, reviews: Path):
        self.states = states
        self.root = root
        self.options = options
        self.reviews = reviews
        self.run_id = now().replace(":", "").replace("+0000", "Z") + "-" + uuid.uuid4().hex[:8]
        self.run_dir = root / "runs" / self.run_id
        self.run_dir.mkdir(parents=True)
        self.events: list[Event] = []
        self.downloaded: list[Download] = []
        self.documents: dict[tuple[str, str], Document] = {}

    def event(self, source: Source, stage: str, status: str, detail: str) -> None:
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
        self.events.append(record)
        LOG.info("%s %s %s: %s", record.jurisdiction, stage, status, detail)

    def select(self, candidates: list[Source]) -> list[Source]:
        candidates.sort(
            key=lambda s: (
                s.discovery_jurisdiction,
                s.discovered_via != "curated_seed",
                s.url,
            )
        )
        counts: dict[str, int] = {}
        selected: list[Source] = []
        for source in candidates:
            state = source.discovery_jurisdiction
            counts[state] = counts.get(state, 0) + 1
            if counts[state] <= self.options.max_pdfs_per_state:
                selected.append(source)
            else:
                self.event(source, "fetch", "skipped", "Per-jurisdiction candidate download budget")
        atomic_json(
            self.run_dir / "candidates.json", [s.model_dump(mode="json") for s in candidates]
        )
        return selected

    def cached_download(self, receipt: Path, source: Source) -> Download | None:
        if not receipt.exists() or self.options.refresh:
            return None
        try:
            cached = Download.model_validate_json(receipt.read_text())
            path = within(self.root, cached.path)
        except (ValueError, OSError):
            return None
        if (
            cached.source.url != source.url
            or cached.source.discovery_jurisdiction != source.discovery_jurisdiction
            or cached.source.credential_format != source.credential_format
        ):
            return None
        if (
            path.is_file()
            and path.stat().st_size == cached.size_bytes
            and digest(path) == cached.sha256
        ):
            return cached
        return None

    async def fetch_one(
        self, source: Source, transport: Transport, slots: asyncio.Semaphore
    ) -> None:
        async with slots:
            key = hashlib.sha256((source.discovery_jurisdiction + source.url).encode()).hexdigest()
            receipt = self.root / "cache" / "downloads" / f"{key}.json"
            try:
                cached = self.cached_download(receipt, source)
                if cached is not None:
                    self.downloaded.append(cached)
                    self.event(source, "fetch", "cached", cached.sha256)
                    return
                result = await transport.download(source, self.root, self.options)
                self.downloaded.append(result)
                atomic_json(receipt, result.model_dump(mode="json"))
                self.event(source, "fetch", "ok", f"{result.size_bytes} bytes; {result.sha256}")
            except Exception as exc:
                self.event(source, "fetch", "failed", f"{type(exc).__name__}: {exc}")

    async def fetch(self) -> None:
        async with httpx.AsyncClient(
            http2=True,
            timeout=20.0,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
            limits=httpx.Limits(max_connections=15, max_keepalive_connections=15),
        ) as client:
            transport = Transport(client)
            candidates, discovery_events = await discover_all(
                self.states,
                transport,
                self.options.crawl_pages,
            )
            self.events.extend(discovery_events)
            selected = self.select(candidates)
            slots = asyncio.Semaphore(15)
            await asyncio.gather(*(self.fetch_one(s, transport, slots) for s in selected))

    def cached_document(self, download: Download) -> Document | None:
        receipt = (
            self.root
            / download.source.discovery_jurisdiction
            / "derived"
            / download.sha256
            / fingerprint(self.options)
            / "document.json"
        )
        if not receipt.exists():
            return None
        try:
            cached = Document.model_validate_json(receipt.read_text())
        except (ValueError, OSError):
            return None
        if (
            cached.download.sha256 != download.sha256
            or cached.download.source.discovery_jurisdiction
            != download.source.discovery_jurisdiction
        ):
            return None
        if not validate_document(cached, self.root):
            return cached.model_copy(update={"download": download})
        return None

    async def extract_one(
        self,
        download: Download,
        pool: ProcessPoolExecutor,
        slots: asyncio.Semaphore,
    ) -> None:
        async with slots:
            try:
                result = self.cached_document(download)
                if result is not None:
                    status, detail = "cached", download.sha256
                else:
                    loop = asyncio.get_running_loop()
                    result = await loop.run_in_executor(
                        pool,
                        extract,
                        download,
                        str(self.root),
                        self.options,
                    )
                    status = "ok"
                    detail = (
                        f"{result.page_count} pages; {len(result.assets)} assets; "
                        f"{result.relevance}"
                    )
                self.documents[(download.source.discovery_jurisdiction, download.sha256)] = result
                self.event(download.source, "extract", status, detail)
            except Exception as exc:
                self.event(download.source, "extract", "failed", f"{type(exc).__name__}: {exc}")

    async def extract_all(self) -> None:
        previous = self.root / MANIFEST_FILENAME
        if previous.exists():
            documents = Manifest.model_validate_json(previous.read_text()).documents
            self.documents = {
                (d.download.source.discovery_jurisdiction, d.download.sha256): d for d in documents
            }
        unique = {(d.source.discovery_jurisdiction, d.sha256): d for d in self.downloaded}
        slots = asyncio.Semaphore(self.options.workers)
        with ProcessPoolExecutor(
            max_workers=self.options.workers,
            mp_context=multiprocessing.get_context("spawn"),
        ) as pool:
            await asyncio.gather(*(self.extract_one(d, pool, slots) for d in unique.values()))

    def publish(self) -> Manifest:
        ordered = sorted(
            self.documents.values(),
            key=lambda d: (
                d.download.source.discovery_jurisdiction,
                d.download.sha256,
            ),
        )
        manifest = Manifest(
            generated_at=now(),
            run_id=self.run_id,
            source_revision=revision(),
            requested_jurisdictions=self.states,
            options=self.options,
            documents=ordered,
            reviews=load_reviews(self.reviews, ordered),
        )
        ledger = [e.model_dump(mode="json") for e in self.events]
        atomic_json(self.run_dir / "events.json", ledger)
        atomic_json(self.run_dir / MANIFEST_FILENAME, manifest.model_dump(mode="json"))
        atomic_json(self.root / "events.json", ledger)
        atomic_json(self.root / MANIFEST_FILENAME, manifest.model_dump(mode="json"))
        write_reports(self.root, manifest, self.events)
        atomic_json(
            self.root / "downloads.json", [d.model_dump(mode="json") for d in self.downloaded]
        )
        return manifest


async def harvest(
    states: list[str],
    root: Path,
    options: Options,
    reviews_path: Path,
) -> Manifest:
    root = await asyncio.to_thread(root.resolve)
    root.mkdir(parents=True, exist_ok=True)
    run = HarvestRun(states, root, options, reviews_path)
    await run.fetch()
    await run.extract_all()
    return run.publish()
