"""Independent private HTML-gallery collection; never changes PDF coverage/cohorts."""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx
from pydantic import Field

from .gallery_html import discover_images, lead_priority
from .gallery_inventory import GalleryInventory
from .gallery_raster import validate_raster
from .gallery_seeds import HTML_GALLERY_SEEDS
from .models import Record
from .network import USER_AGENT, FetchError, Transport, content_length
from .paths import contained_path
from .storage import atomic_json, digest, now


def error_reason(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"http_status_{error.response.status_code}"
    if isinstance(error, (FetchError, ValueError)):
        return type(error).__name__ + ":" + str(error)[:300]
    return type(error).__name__


HTML_MEDIA_TYPE = "text/html"


class GalleryOptions(Record):
    max_pages: int = Field(default=40, ge=1, le=500)
    max_assets: int = Field(default=200, ge=1, le=2000)
    max_html_bytes: int = Field(default=2_000_000, ge=1, le=5_000_000)
    max_image_bytes: int = Field(default=12_000_000, ge=1, le=30_000_000)
    max_total_bytes: int = Field(default=256_000_000, ge=1)
    max_pixels: int = Field(default=20_000_000, ge=1, le=40_000_000)
    max_links: int = Field(default=200, ge=1, le=1000)
    concurrency: int = Field(default=2, ge=1, le=4)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def retain(root: Path, folder: str, data: bytes, extension: str) -> tuple[str, str]:
    checksum = sha(data)
    relative = f"{folder}/{checksum}.{extension}"
    target = contained_path(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if digest(target) != checksum:
            raise ValueError("Existing content-addressed object failed integrity verification")
        return relative, checksum
    descriptor, temporary = tempfile.mkstemp(prefix=".gallery-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return relative, checksum


class GalleryJob:
    def __init__(self, root: Path, options: GalleryOptions, transport: Transport) -> None:
        self.root, self.options, self.transport = root, options, transport
        self.inventory = GalleryInventory(root)
        self.remaining = options.max_total_bytes
        self.manifest: dict[str, Any] = {
            "schema_version": 1,
            "track": "html_gallery",
            "run_id": str(uuid.uuid4()),
            "started_at": now(),
            "options": options.model_dump(),
            "pages": self.inventory.records["pages"],
            "assets": self.inventory.records["assets"],
            "aliases": self.inventory.records["aliases"],
            "inventory_parent_run_id": self.inventory.previous_run_id,
            "events": [],
            "page_links": [],
            "run_status": "running",
            "accepted_cohorts": 0,
            "interpretation": (
                "Unreviewed source observations; no cleanliness, pairing, or cohort-date claims"
            ),
        }
        self.requested_assets = 0
        self.queue: list[tuple[str, str]] = []
        self.seen: set[str] = set()
        self.limiter = asyncio.Semaphore(options.concurrency)

    def event(self, collection: str, url: str, status: str, reason: str) -> None:
        self.manifest["events"].append(
            {"at": now(), "collection": collection, "url": url, "status": status, "reason": reason}
        )

    async def fetch(self, url: str) -> tuple[bytes, str, str]:
        async with asyncio.timeout(90), self.transport.stream(url, obey_robots=True) as response:
            media = response.headers.get("content-type", "").partition(";")[0].lower().strip()
            limit = (
                self.options.max_html_bytes
                if media == HTML_MEDIA_TYPE
                else self.options.max_image_bytes
            )
            allowed = min(limit, self.remaining)
            if allowed < 1:
                raise ValueError("Gallery total byte budget exhausted")
            self.remaining -= (
                allowed  # Reserve before awaiting; failed streams consume their reservation.
            )
            expected = content_length(response, allowed)
            data = bytearray()
            async for chunk in response.aiter_bytes():
                if len(data) + len(chunk) > allowed:
                    raise ValueError("Gallery response exceeds byte budget")
                data.extend(chunk)
            if (
                response.headers.get("content-encoding", "identity").lower() == "identity"
                and expected is not None
                and expected != len(data)
            ):
                raise ValueError("Gallery Content-Length mismatch")
            self.remaining += allowed - len(data)
            return bytes(data), str(response.url), response.headers.get("content-type", "")

    def page(
        self, collection: str, data: bytes, final_url: str, method: str
    ) -> list[dict[str, str]]:
        path, checksum = retain(self.root, "html", data, "html")
        self.inventory.observe(
            "pages",
            {
                "collection": collection,
                "url": final_url,
                "path": path,
                "sha256": checksum,
                "size_bytes": len(data),
                "retrieved_at": now(),
                "acquisition_method": method,
                "review_status": "unreviewed",
            },
        )
        leads, rejected = discover_images(data, final_url, self.options.max_links)
        for failure in rejected:
            self.event(collection, failure["url"], "rejected", failure["reason"])
        return [
            {
                **lead,
                "collection": collection,
                "source_page_url": final_url,
                "parent_html_sha256": checksum,
                "parent_html_path": path,
            }
            for lead in leads
        ]

    async def image(self, lead: dict[str, str]) -> None:
        async with self.limiter:
            try:
                data, final_url, media = await self.fetch(lead["url"])
                if media.partition(";")[0].strip().lower() == HTML_MEDIA_TYPE:
                    self.queue.append((lead["collection"], final_url))
                    self.manifest["page_links"].append({**lead, "target_page_url": final_url})
                    self.event(
                        lead["collection"],
                        lead["url"],
                        "html_wrapper",
                        "Queued bounded HTML/media wrapper",
                    )
                    return
                await self.asset(lead, data, final_url, media, "http_transport")
            except (ValueError, OSError, FetchError, httpx.HTTPError) as exc:
                self.event(lead["collection"], lead["url"], "failed", error_reason(exc))

    async def asset(
        self, lead: dict[str, str], data: bytes, final_url: str, media: str, method: str
    ) -> None:
        if len(data) > self.options.max_image_bytes:
            raise ValueError("Image byte budget exceeded")
        # PyMuPDF does not support concurrent use from threads. Native decode is
        # serialized on this job's event-loop thread after the header budget check.
        dimensions = validate_raster(data, media, self.options.max_pixels)
        path, checksum = await asyncio.to_thread(
            retain, self.root, "originals", data, dimensions["format"]
        )
        self.inventory.observe(
            "aliases",
            {
                **lead,
                "final_url": final_url,
                "asset_sha256": checksum,
                "retrieved_at": now(),
                "acquisition_method": method,
                "review_status": "unreviewed",
            },
        )
        self.inventory.observe(
            "assets",
            {
                "sha256": checksum,
                "path": path,
                "size_bytes": len(data),
                "content_type": media,
                **dimensions,
                "review_status": "unreviewed",
                "plate_composition": "unreviewed",
                "accepted_cohort": False,
                "altered": False,
            },
        )

    async def run(self, collections: list[str]) -> None:
        self.queue.extend(
            (code, url) for code in collections for url in HTML_GALLERY_SEEDS.get(code, [])
        )
        while self.queue and len(self.seen) < self.options.max_pages:
            collection, url = self.queue.pop(0)
            if url in self.seen:
                continue
            self.seen.add(url)
            await self.visit(collection, url)
        if self.queue:
            self.event("", "", "skipped", "Gallery HTML page budget exhausted")

    async def visit(self, collection: str, url: str) -> None:
        try:
            data, final_url, media = await self.fetch(url)
            if media.partition(";")[0].strip().lower() != HTML_MEDIA_TYPE:
                raise ValueError("Gallery entry must return HTML")
            leads = self.page(collection, data, final_url, "http_transport")
            remaining = max(0, self.options.max_assets - self.requested_assets)
            selected = sorted(leads, key=lead_priority, reverse=True)[:remaining]
            self.requested_assets += len(selected)
            if len(leads) > remaining:
                self.event(collection, url, "skipped", "Gallery asset request budget exhausted")
            await asyncio.gather(*(self.image(lead) for lead in selected))
        except (ValueError, OSError, FetchError, httpx.HTTPError) as exc:
            self.event(collection, url, "failed", error_reason(exc))

    def finish(self) -> dict[str, Any]:
        self.manifest["finished_at"] = now()
        self.manifest["run_observations"] = self.inventory.run_counts()
        atomic_json(self.root / "runs" / f"{self.manifest['run_id']}.json", self.manifest)
        atomic_json(self.root / "manifest.json", self.manifest)
        return self.manifest


async def harvest_images(
    collections: list[str],
    root: Path,
    options: GalleryOptions,
    import_paths: list[Path] | None = None,
) -> dict[str, Any]:
    from .gallery_import import import_browser_manifest

    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        job = GalleryJob(root, options, Transport(client))
        try:
            await job.run(collections)
            for path in import_paths or []:
                await import_browser_manifest(job, path)
            job.manifest["run_status"] = "complete"
        finally:
            if job.manifest["run_status"] == "running":
                job.manifest["run_status"] = "interrupted"
            result = job.finish()
        return result
