"""Bounded streaming transport. Every redirect is checked before it is followed."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import os
import socket
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

from .models import Download, Options, Source
from .seeds import FEDERAL_CODE, FEDERAL_PUBLISHER_HOSTS, LEGACY_OFFICIAL_HOSTS, STATE_DOMAINS
from .storage import now

USER_AGENT = "state-id-harvester/0.1 (+https://github.com/Kenshiki-Labs/state-id-harvester)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    pass


def official_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        permitted = (
            parts.scheme == "https"
            and parts.username is None
            and parts.password is None
            and parts.port in (None, 443)
            and (host.endswith(".gov") or host in LEGACY_OFFICIAL_HOSTS)
        )
    except ValueError as exc:
        raise FetchError("Malformed official HTTPS URL") from exc
    if not permitted:
        raise FetchError("URL is outside the official HTTPS host policy")
    return urlunsplit(("https", parts.netloc.lower(), parts.path or "/", parts.query, ""))


def check_pdf_prefix(prefix: bytes | bytearray) -> None:
    if b"%PDF-" not in prefix[:1024]:
        raise FetchError("Missing PDF signature in first 1024 bytes")


def publisher_jurisdiction(host: str) -> str | None:
    if host in FEDERAL_PUBLISHER_HOSTS:
        return FEDERAL_CODE
    aliases = {
        "wyoleg.gov": "WY",
        "newmexico.gov": "NM",
        "ncdot.gov": "NC",
        "txdmv.gov": "TX",
        "ksrevenue.gov": "KS",
        "mvdmt.gov": "MT",
        "expresslane.org": "LA",
        "scdmvonline.com": "SC",
        "dot.state.wy.us": "WY",
    }
    for domain, state in {**{v: k for k, v in STATE_DOMAINS.items()}, **aliases}.items():
        if host == domain or host.endswith("." + domain):
            return state
    return None


def content_length(response: httpx.Response, limit: int) -> int | None:
    value = response.headers.get("content-length")
    if value is None:
        return None
    if not value or not value.isascii() or not value.isdecimal():
        raise FetchError("Malformed Content-Length")
    if len(value) > 20 or int(value) > limit:
        raise FetchError("Content-Length exceeds byte limit")
    return int(value)


def retry_delay(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("retry-after", "")
    if value.isascii() and value.isdecimal():
        return min(float(value), 20.0)
    return 2.0**attempt


async def complete_io[T](operation: Callable[[], T]) -> T:
    """Finish an in-flight file operation before cancellation can close its file."""
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class DownloadFile:
    """Own the partial file; all methods touching the filesystem run in a worker thread."""

    def __init__(self, directory: Path, options: Options) -> None:
        self.directory = directory
        self.options = options
        self.path: Path | None = None
        self.destination: BinaryIO | None = None
        self.total = 0
        self.prefix = bytearray()
        self.hasher = hashlib.sha256()

    def open(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".download-", dir=self.directory)
        self.path = Path(temporary)
        try:
            self.destination = os.fdopen(descriptor, "wb")
        except OSError:
            os.close(descriptor)
            raise

    def write(self, chunk: bytes) -> None:
        self.total += len(chunk)
        if self.total > self.options.max_pdf_bytes:
            raise FetchError("Stream exceeds PDF byte limit")
        if len(self.prefix) < 1024:
            self.prefix.extend(chunk[: 1024 - len(self.prefix)])
            if len(self.prefix) == 1024:
                check_pdf_prefix(self.prefix)
        self.hasher.update(chunk)
        if self.destination is None:
            raise FetchError("Download file is not open")
        self.destination.write(chunk)

    def finish(self, expected_length: int | None) -> str:
        check_pdf_prefix(self.prefix)
        if self.total < self.options.min_pdf_bytes:
            raise FetchError("PDF is below minimum byte size")
        if expected_length is not None and self.total != expected_length:
            raise FetchError("Content-Length does not match PDF byte size")
        return self.hasher.hexdigest()

    def publish(self, target: Path) -> None:
        if self.destination is None or self.path is None:
            raise FetchError("Download file is not open")
        self.destination.close()
        os.replace(self.path, target)
        self.path = None

    def cleanup(self) -> None:
        if self.destination is not None:
            self.destination.close()
        if self.path is not None:
            self.path.unlink(missing_ok=True)


def download_record(
    source: Source, response: httpx.Response, root: Path, target: Path, sha: str, total: int
) -> Download:
    host = urlsplit(str(response.url)).hostname or ""
    return Download(
        source=source,
        final_url=str(response.url),
        retrieved_at=now(),
        sha256=sha,
        size_bytes=total,
        path=target.relative_to(root).as_posix(),
        content_type=response.headers.get("content-type", ""),
        publisher_host=host,
        publisher_jurisdiction=publisher_jurisdiction(host),
        etag=response.headers.get("etag"),
        last_modified=response.headers.get("last-modified"),
    )


class Transport:
    def __init__(self, client: httpx.AsyncClient, *, check_dns: bool = True) -> None:
        self.client = client
        self.check_dns = check_dns
        self.semaphore = asyncio.Semaphore(15)
        self.host_limits: dict[str, asyncio.Semaphore] = {}
        self.robots: dict[str, RobotFileParser] = {}
        self.robots_locks: dict[str, asyncio.Lock] = {}

    async def validate(self, url: str) -> str:
        normalized = official_url(url)
        host = urlsplit(normalized).hostname or ""
        if self.check_dns:
            try:
                addresses = await asyncio.to_thread(socket.getaddrinfo, host, 443)
            except OSError as exc:
                raise FetchError("Official host DNS resolution failed") from exc
            if not addresses or any(not public_address(str(row[4][0])) for row in addresses):
                raise FetchError("Host resolved to a non-public address")
        return normalized

    @asynccontextmanager
    async def request(self, url: str) -> AsyncIterator[httpx.Response]:
        host = urlsplit(url).hostname or ""
        limiter = self.host_limits.setdefault(host, asyncio.Semaphore(2))
        for attempt in range(3):
            async with (
                self.semaphore,
                limiter,
                self.client.stream("GET", url, follow_redirects=False) as response,
            ):
                if response.status_code not in RETRYABLE_STATUS or attempt == 2:
                    if not response.is_redirect:
                        response.raise_for_status()
                    yield response
                    return
                delay = retry_delay(response, attempt)
            await asyncio.sleep(delay)

    @asynccontextmanager
    async def stream(self, url: str, *, obey_robots: bool = False) -> AsyncIterator[httpx.Response]:
        current = await self.validate(url)
        for _redirect in range(6):
            if obey_robots and not await self.allowed(current):
                raise FetchError("robots.txt disallows this URL")
            async with self.request(current) as response:
                if not response.is_redirect:
                    yield response
                    return
                location = response.headers.get("location")
                if not location:
                    raise FetchError("Redirect without Location")
                current = await self.validate(urljoin(current, location))
        raise FetchError("Redirect limit exceeded")

    async def bytes(
        self, url: str, limit: int = 2_000_000, *, obey_robots: bool = False
    ) -> tuple[bytes, str, str]:
        async with asyncio.timeout(90), self.stream(url, obey_robots=obey_robots) as response:
            content_length(response, limit)
            data = bytearray()
            async for chunk in response.aiter_bytes():
                if len(data) + len(chunk) > limit:
                    raise FetchError("Response exceeds byte limit")
                data.extend(chunk)
            return bytes(data), str(response.url), response.headers.get("content-type", "")

    async def allowed(self, url: str) -> bool:
        url = await self.validate(url)
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        lock = self.robots_locks.setdefault(origin, asyncio.Lock())
        async with lock:
            if origin not in self.robots:
                self.robots[origin] = await self.robots_policy(origin)
        return self.robots[origin].can_fetch(USER_AGENT, url)

    async def robots_policy(self, origin: str) -> RobotFileParser:
        parser = RobotFileParser()
        try:
            data, _, _ = await self.bytes(origin + "/robots.txt", 512_000)
            parser.parse(data.decode("utf-8", errors="replace").splitlines())
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (404, 410):
                parser.parse([])
            elif exc.response.status_code in (401, 403):
                parser.parse(["User-agent: *", "Disallow: /"])
            else:
                raise
        return parser

    async def download(self, source: Source, root: Path, options: Options) -> Download:
        directory = root / source.discovery_jurisdiction / "raw_pdfs"
        destination = DownloadFile(directory, options)
        try:
            await complete_io(destination.open)
            async with asyncio.timeout(90), self.stream(source.url, obey_robots=True) as response:
                expected = content_length(response, options.max_pdf_bytes)
                # Content-Length counts encoded wire bytes, while aiter_bytes yields decoded bytes.
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    expected = None
                async for chunk in response.aiter_bytes():
                    await complete_io(partial(destination.write, chunk))
                sha = destination.finish(expected)
                target = directory / f"{sha}.pdf"
                result = download_record(source, response, root, target, sha, destination.total)
            await complete_io(partial(destination.publish, target))
            return result
        finally:
            await complete_io(destination.cleanup)


def public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        return address.is_global and not address.is_multicast
    except ValueError:
        return False
