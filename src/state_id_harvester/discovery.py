"""Finite official-page discovery plus optional, bounded search-provider requests."""

from __future__ import annotations

import asyncio
import os
import re
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin

import httpx

from .models import Event, Source
from .network import FetchError, Transport, official_url
from .seeds import DORK_TEMPLATES, GOLDEN_SEED_PDFS, LANDING_PAGES, STATE_DOMAINS
from .storage import now

RELEVANT = re.compile(
    r"secur|credential|new.?design|new.?card|sample|brochure|fraud|identif|driver|licen[cs]e|retail|train",
    re.I,
)


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.current: str | None = None
        self.label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self.current = values["href"]
            self.label = []

    def handle_data(self, data: str) -> None:
        if self.current:
            self.label.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current:
            self.links.append((self.current, " ".join(self.label)))
            self.current = None


def pdf_link(url: str, label: str) -> bool:
    return bool(re.search(r"\.pdf(?:[?#]|$)|/doc(?:ument)?s?/|/download(?:[/?]|$)", url, re.I)) or (
        "pdf" in label.lower()
    )


async def search(
    state: str,
    client: httpx.AsyncClient,
    provider: str,
    key: str,
) -> tuple[list[Source], list[Event]]:
    sources: list[Source] = []
    events: list[Event] = []
    for template in DORK_TEMPLATES:
        query = template.format(domain=STATE_DOMAINS[state])
        try:
            # discover_all serializes provider requests, including across states.
            if provider == "serper":
                response = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": key},
                    json={"q": query, "num": 10},
                )
                response.raise_for_status()
                urls = [item.get("link", "") for item in response.json().get("organic", [])]
            else:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"X-Subscription-Token": key},
                    params={"q": query, "count": 10},
                )
                response.raise_for_status()
                urls = [
                    item.get("url", "")
                    for item in response.json().get("web", {}).get("results", [])
                ]
            for url in urls:
                try:
                    sources.append(
                        Source(
                            discovery_jurisdiction=state,
                            url=official_url(url),
                            discovered_via=f"search:{provider}:{query}",
                        )
                    )
                except (FetchError, ValueError):
                    continue
            events.append(
                Event(
                    at=now(),
                    jurisdiction=state,
                    url=provider,
                    stage="discovery",
                    status="ok",
                    detail=f"Search returned {len(urls)} results: {query}",
                )
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            # Never include provider request headers/keys in an error ledger.
            events.append(
                Event(
                    at=now(),
                    jurisdiction=state,
                    url=provider,
                    stage="discovery",
                    status="failed",
                    detail=f"Search request failed: {query}",
                )
            )
        await asyncio.sleep(1.1)
    return sources, events


async def discover(
    state: str,
    transport: Transport,
    crawl_pages: int,
) -> tuple[list[Source], list[Event]]:
    found = [
        Source(discovery_jurisdiction=state, url=url, discovered_via="curated_seed")
        for url in GOLDEN_SEED_PDFS.get(state, [])
    ]
    events: list[Event] = []
    queue = list(LANDING_PAGES[state])
    seen: set[str] = set()
    for _ in range(crawl_pages):
        if not queue:
            break
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            if not await transport.allowed(url):
                raise FetchError("robots.txt disallows this URL")
            data, final_url, content_type = await transport.bytes(url)
            if b"%PDF-" in data[:1024]:
                found.append(
                    Source(discovery_jurisdiction=state, url=url, discovered_via="official_page")
                )
                continue
            if "html" not in content_type.lower():
                raise FetchError("Entry point did not return HTML or a PDF")
            parser = Links()
            parser.feed(data.decode("utf-8", errors="replace"))
            next_pages: list[tuple[int, str]] = []
            for href, label in parser.links:
                try:
                    candidate = official_url(urljoin(final_url, href))
                except (ValueError, FetchError):
                    continue
                description = unquote(candidate) + " " + label
                if not RELEVANT.search(description):
                    continue
                if pdf_link(candidate, label):
                    found.append(
                        Source(
                            discovery_jurisdiction=state,
                            url=candidate,
                            discovered_via=final_url,
                            link_text=label,
                        )
                    )
                elif candidate not in seen and candidate not in queue:
                    score = len(
                        re.findall(r"secur|sample|new.?design|brochure|fraud", description, re.I)
                    )
                    next_pages.append((-score, candidate))
            queue = [u for _, u in sorted(next_pages)] + queue
            queue = list(dict.fromkeys(queue))[:100]
            events.append(
                Event(
                    at=now(),
                    jurisdiction=state,
                    url=url,
                    stage="discovery",
                    status="ok",
                    detail=f"Parsed {len(parser.links)} official-page links",
                )
            )
        except (FetchError, httpx.HTTPError, OSError, TimeoutError, ValueError) as exc:
            events.append(
                Event(
                    at=now(),
                    jurisdiction=state,
                    url=url,
                    stage="discovery",
                    status="failed",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
        await asyncio.sleep(0.2)
    if not crawl_pages:
        events.append(
            Event(
                at=now(),
                jurisdiction=state,
                url="",
                stage="discovery",
                status="skipped",
                detail="Official-page discovery disabled by configuration",
            )
        )
    return found, events


async def discover_all(
    states: list[str],
    transport: Transport,
    crawl_pages: int,
) -> tuple[list[Source], list[Event]]:
    results = await asyncio.gather(*(discover(s, transport, crawl_pages) for s in states))
    found = [source for sources, _ in results for source in sources]
    events = [event for _, ledger in results for event in ledger]
    provider = "serper" if os.environ.get("SERPER_API_KEY") else "brave"
    key = os.environ.get("SERPER_API_KEY") or os.environ.get("BRAVE_API_KEY")
    if key:
        # One request at a time, >=1.1s between provider requests (including across states).
        for state in states:
            sources, ledger = await search(state, transport.client, provider, key)
            found.extend(sources)
            events.extend(ledger)
    else:
        events.extend(
            Event(
                at=now(),
                jurisdiction=s,
                url="",
                stage="discovery",
                status="skipped",
                detail="No search API key; using curated seeds and bounded official pages",
            )
            for s in states
        )
    unique = {(s.discovery_jurisdiction, s.url): s for s in reversed(found)}
    return list(unique.values()), events
