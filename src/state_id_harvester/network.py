"""Bounded streaming transport. Every redirect is checked before it is followed."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import os
import socket
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

from .models import Download, Options, Source
from .seeds import LEGACY_OFFICIAL_HOSTS, STATE_DOMAINS
from .storage import now

USER_AGENT = "state-id-harvester/0.1 (+https://github.com/Kenshiki-Labs/state-id-harvester)"


class FetchError(Exception):
    pass


def official_url(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443)
        or not (host.endswith(".gov") or host in LEGACY_OFFICIAL_HOSTS)
    ):
        raise FetchError("URL is outside the official HTTPS host policy")
    return urlunsplit(("https", parts.netloc.lower(), parts.path or "/", parts.query, ""))


def check_pdf_prefix(prefix: bytes | bytearray) -> None:
    if b"%PDF-" not in prefix[:1024]:
        raise FetchError("Missing PDF signature in first 1024 bytes")


def publisher_jurisdiction(host: str) -> str | None:
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


class Transport:
    def __init__(self, client: httpx.AsyncClient, *, check_dns: bool = True) -> None:
        self.client = client
        self.check_dns = check_dns
        self.semaphore = asyncio.Semaphore(15)
        self.host_limits: dict[str, asyncio.Semaphore] = {}
        self.validated_hosts: set[str] = set()
        self.robots: dict[str, RobotFileParser] = {}
        self.robots_locks: dict[str, asyncio.Lock] = {}

    async def validate(self, url: str) -> str:
        normalized = official_url(url)
        host = urlsplit(normalized).hostname or ""
        if self.check_dns and host not in self.validated_hosts:
            addresses = await asyncio.to_thread(socket.getaddrinfo, host, 443)
            if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
                raise FetchError("Host resolved to a non-public address")
            self.validated_hosts.add(host)
        return normalized

    @asynccontextmanager
    async def stream(self, url: str) -> AsyncIterator[httpx.Response]:
        current = await self.validate(url)
        for _redirect in range(6):
            host = urlsplit(current).hostname or ""
            limiter = self.host_limits.setdefault(host, asyncio.Semaphore(2))
            redirected = False
            for attempt in range(3):
                async with self.semaphore, limiter:
                    async with self.client.stream(
                        "GET", current, follow_redirects=False
                    ) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise FetchError("Redirect without Location")
                            current = await self.validate(urljoin(current, location))
                            redirected = True
                            break
                        if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                            retry = response.headers.get("retry-after", "")
                            delay = min(float(retry), 20.0) if retry.isdigit() else 2.0**attempt
                        else:
                            response.raise_for_status()
                            yield response
                            return
                await asyncio.sleep(delay)
            if not redirected:
                raise FetchError("Retry budget exhausted")
        raise FetchError("Redirect limit exceeded")

    async def bytes(self, url: str, limit: int = 2_000_000) -> tuple[bytes, str, str]:
        async with asyncio.timeout(90), self.stream(url) as response:
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
                self.robots[origin] = parser
        return self.robots[origin].can_fetch(USER_AGENT, url)

    async def download(self, source: Source, root: Path, options: Options) -> Download:
        if not await self.allowed(source.url):
            raise FetchError("robots.txt disallows this URL")
        target_dir = root / source.discovery_jurisdiction / "raw_pdfs"
        target_dir.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".download-", dir=target_dir)
        total = 0
        prefix = bytearray()
        hasher = hashlib.sha256()
        try:
            with os.fdopen(descriptor, "wb") as destination:
                async with asyncio.timeout(90), self.stream(source.url) as response:
                    length = response.headers.get("content-length", "")
                    if length.isdigit() and int(length) > options.max_pdf_bytes:
                        raise FetchError("Content-Length exceeds PDF limit")
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > options.max_pdf_bytes:
                            raise FetchError("Stream exceeds PDF byte limit")
                        if len(prefix) < 1024:
                            prefix.extend(chunk[: 1024 - len(prefix)])
                            if len(prefix) == 1024:
                                check_pdf_prefix(prefix)
                        hasher.update(chunk)
                        destination.write(chunk)
                    check_pdf_prefix(prefix)
                    if total < options.min_pdf_bytes:
                        raise FetchError("PDF is below minimum byte size")
                    sha = hasher.hexdigest()
                    target = target_dir / f"{sha}.pdf"
                    result = Download(
                        source=source,
                        final_url=str(response.url),
                        retrieved_at=now(),
                        sha256=sha,
                        size_bytes=total,
                        path=target.relative_to(root).as_posix(),
                        content_type=response.headers.get("content-type", ""),
                        publisher_host=urlsplit(str(response.url)).hostname or "",
                        publisher_jurisdiction=publisher_jurisdiction(
                            urlsplit(str(response.url)).hostname or ""
                        ),
                        etag=response.headers.get("etag"),
                        last_modified=response.headers.get("last-modified"),
                    )
            os.replace(temporary, target)
            return result
        finally:
            await asyncio.to_thread(Path(temporary).unlink, missing_ok=True)
