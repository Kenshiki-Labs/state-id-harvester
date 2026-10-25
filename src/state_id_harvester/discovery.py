"""Finite official-page discovery plus optional, bounded search-provider requests."""

from __future__ import annotations

import asyncio
import os
import re
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import unquote, urljoin

import httpx

from .models import Event, Source
from .network import FetchError, Transport, official_url
from .seeds import (
    COLLECTION_DOMAINS,
    DORK_TEMPLATES,
    FEDERAL_CODE,
    collection_landing_pages,
    collection_pdf_seeds,
)
from .storage import now

RELEVANT = re.compile(
    r"secur|credential|new.?design|new.?card|sample|brochure|fraud|identif|driver|licen[cs]e|retail|train",
    re.I,
)
FEDERAL_RELEVANT = re.compile(
    RELEVANT.pattern + r"|passport|resident|employment|\bPIV\b|personal.identity|carrier", re.I
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


def discovery_event(
    state: str, url: str, status: Literal["ok", "failed", "cached", "skipped"], detail: str
) -> Event:
    return Event(
        at=now(), jurisdiction=state, url=url, stage="discovery", status=status, detail=detail
    )


def official_sources(state: str, urls: list[str], via: str) -> list[Source]:
    found: list[Source] = []
    for url in urls:
        try:
            found.append(
                Source(discovery_jurisdiction=state, url=official_url(url), discovered_via=via)
            )
        except FetchError:
            continue
    return found


async def search_urls(client: httpx.AsyncClient, provider: str, key: str, query: str) -> list[str]:
    if provider == "serper":
        response = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key},
            json={"q": query, "num": 10},
        )
    else:
        response = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": key},
            params={"q": query, "count": 10},
        )
    response.raise_for_status()
    payload = response.json()
    results = (
        payload.get("organic", [])
        if provider == "serper"
        else payload.get("web", {}).get("results", [])
    )
    link_key = "link" if provider == "serper" else "url"
    return [
        item[link_key]
        for item in results
        if isinstance(item, dict) and isinstance(item.get(link_key), str)
    ]


async def search(
    state: str,
    client: httpx.AsyncClient,
    provider: str,
    key: str,
) -> tuple[list[Source], list[Event]]:
    sources: list[Source] = []
    events: list[Event] = []
    for template in DORK_TEMPLATES:
        query = template.format(domain=COLLECTION_DOMAINS[state])
        try:
            # discover_all serializes provider requests, including across collections.
            urls = await search_urls(client, provider, key, query)
            sources.extend(official_sources(state, urls, f"search:{provider}:{query}"))
            events.append(
                discovery_event(
                    state, provider, "ok", f"Search returned {len(urls)} results: {query}"
                )
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            # Never include provider request headers/keys in an error ledger.
            events.append(
                discovery_event(state, provider, "failed", f"Search request failed: {query}")
            )
        await asyncio.sleep(1.1)
    return sources, events


def classify_links(
    state: str, final_url: str, parser: Links, seen: set[str]
) -> tuple[list[Source], list[str]]:
    found: list[Source] = []
    next_pages: list[tuple[int, str]] = []
    relevant = FEDERAL_RELEVANT if state == FEDERAL_CODE else RELEVANT
    for href, label in parser.links:
        try:
            candidate = official_url(urljoin(final_url, href))
        except (ValueError, FetchError):
            continue
        description = unquote(candidate) + " " + label
        if not relevant.search(description):
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
        elif candidate not in seen:
            score = len(re.findall(r"secur|sample|new.?design|brochure|fraud", description, re.I))
            next_pages.append((-score, candidate))
    return found, [url for _, url in sorted(next_pages)]


async def discover_page(
    state: str, url: str, transport: Transport, seen: set[str]
) -> tuple[list[Source], list[str], str]:
    data, final_url, content_type = await transport.bytes(url, obey_robots=True)
    if b"%PDF-" in data[:1024]:
        return (
            [Source(discovery_jurisdiction=state, url=url, discovered_via="official_page")],
            [],
            "Entry point returned a PDF",
        )
    if "html" not in content_type.lower():
        raise FetchError("Entry point did not return HTML or a PDF")
    parser = Links()
    parser.feed(data.decode("utf-8", errors="replace"))
    found, next_pages = classify_links(state, final_url, parser, seen)
    return found, next_pages, f"Parsed {len(parser.links)} official-page links"


async def discover(
    state: str,
    transport: Transport,
    crawl_pages: int,
) -> tuple[list[Source], list[Event]]:
    found = official_sources(state, collection_pdf_seeds(state), "curated_seed")
    events: list[Event] = []
    queue = list(collection_landing_pages(state))
    seen: set[str] = set()
    for _ in range(crawl_pages):
        if not queue:
            break
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            sources, next_pages, detail = await discover_page(state, url, transport, seen)
            found.extend(sources)
            queue = list(dict.fromkeys(next_pages + queue))[:100]
            events.append(discovery_event(state, url, "ok", detail))
        except (FetchError, httpx.HTTPError, OSError, ValueError) as exc:
            events.append(discovery_event(state, url, "failed", f"{type(exc).__name__}: {exc}"))
        await asyncio.sleep(0.2)
    if not crawl_pages:
        events.append(
            discovery_event(
                state, "", "skipped", "Official-page discovery disabled by configuration"
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
            discovery_event(
                s,
                "",
                "skipped",
                "No search API key; using curated seeds and bounded official pages",
            )
            for s in states
        )
    unique = {(s.discovery_jurisdiction, s.url): s for s in reversed(found)}
    return list(unique.values()), events
