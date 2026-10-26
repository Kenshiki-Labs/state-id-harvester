"""Bounded HTML evidence discovery; captions and dates remain unreviewed source text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin

from .network import FetchError, official_url

VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
IGNORED = {"script", "style", "noscript"}
IMAGE_LINK = re.compile(r"\.(?:jpe?g|png|webp)(?:[?#]|$)|/media(?:/|$)|/download(?:[/?]|$)", re.I)


@dataclass
class Node:
    tag: str
    attrs: dict[str, str | None]
    parent: Node | None
    children: list[Node | str] = field(default_factory=list)

    def text(self, limit: int = 6000) -> str:
        parts: list[str] = []
        pending: list[Node | str] = [self]
        length = 0
        while pending and length < limit:
            item = pending.pop()
            if isinstance(item, str):
                parts.append(item[: limit - length])
                length += len(item)
            elif item.tag not in IGNORED:
                pending.extend(reversed(item.children))
        return " ".join(" ".join(parts).split())[:limit]


class GalleryHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document", {}, None)
        self.stack = [self.root]
        self.nodes: list[Node] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.nodes) >= 20000 or len(self.stack) >= 64:
            raise ValueError("HTML structural budget exceeded")
        node = Node(tag, dict(attrs), self.stack[-1])
        self.stack[-1].children.append(node)
        self.nodes.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if self.stack[-1].tag not in IGNORED:
            self.stack[-1].children.append(data)


def valid_descriptor(value: str) -> bool:
    number = value[:-1]
    if value.endswith("w"):
        return re.fullmatch(r"[1-9]\d{0,5}", number, re.ASCII) is not None
    if not value.endswith("x"):
        return False
    if re.fullmatch(r"(?:\d{1,2}(?:\.\d{1,3})?|\.\d{1,3})", number, re.ASCII) is None:
        return False
    return 0 < float(number) <= 10


def srcset_urls(value: str) -> list[str]:
    """Reject ambiguous/data-URL lists rather than trusting arbitrary descriptors."""
    entries = value.split(",")
    if len(entries) > 32:
        raise ValueError("srcset candidate budget exceeded")
    result: list[str] = []
    for entry in entries:
        words = entry.split()
        if not 1 <= len(words) <= 2 or words[0].lower().startswith("data:"):
            raise ValueError("Malformed srcset")
        if len(words) == 2 and not valid_descriptor(words[1]):
            raise ValueError("Invalid srcset descriptor")
        result.append(words[0])
    return result


def ancestor(node: Node, tags: set[str]) -> Node | None:
    current = node.parent
    while current is not None:
        if current.tag in tags:
            return current
        current = current.parent
    return None


def node_urls(node: Node) -> list[str]:
    if node.tag == "a":
        href = node.attrs.get("href") or ""
        return [href] if IMAGE_LINK.search(href) or "view image" in node.text().lower() else []
    if node.tag not in {"img", "source"}:
        return []
    if node.tag == "source" and ancestor(node, {"picture"}) is None:
        return []
    urls = [
        node.attrs[key]
        for key in ("src", "data-src", "data-lazy-src", "data-original")
        if node.attrs.get(key)
    ]
    for key in ("srcset", "data-srcset"):
        if node.attrs.get(key):
            urls.extend(srcset_urls(node.attrs[key] or ""))
    return [url for url in urls if url is not None]


def image_lead(node: Node, url: str, heading: str) -> dict[str, str]:
    context = ancestor(node, {"figure", "tr", "td", "section", "article", "div"})
    caption = ancestor(node, {"figure"})
    row = ancestor(node, {"tr"})
    table = ancestor(node, {"table"})
    return {
        "url": url,
        "element": node.tag,
        "alt": node.attrs.get("alt") or "",
        "heading": heading,
        "caption": caption.text() if caption else "",
        "context": context.text() if context else node.text(),
        "table_row_context": row.text() if row else "",
        "table_context": table.text() if table else "",
    }


def node_leads(
    node: Node, base_url: str, heading: str
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    leads: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for raw in node_urls(node):
        try:
            if len(raw) > 4096 or any(ord(char) < 32 or ord(char) == 127 for char in raw):
                raise FetchError("Malformed image URL")
            url = official_url(urljoin(base_url, raw))
        except (FetchError, ValueError):
            rejected.append({"url": raw[:2000], "reason": "Nonofficial or unsafe image URL"})
            continue
        leads.append(image_lead(node, url, heading))
    return leads, rejected


def discover_images(
    html: bytes, page_url: str, limit: int
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    parser = GalleryHTML()
    parser.feed(html.decode("utf-8", errors="replace"))
    base = next(
        (
            node.attrs["href"]
            for node in parser.nodes
            if node.tag == "base" and node.attrs.get("href")
        ),
        None,
    )
    resolution_url = official_url(urljoin(page_url, base)) if base else page_url
    heading = ""
    leads: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for node in parser.nodes:
        if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            heading = node.text(1000)
        try:
            found, denied = node_leads(node, resolution_url, heading)
        except ValueError as exc:
            found, denied = [], [{"url": page_url, "reason": str(exc)}]
        remaining = max(0, limit - len(leads) - len(rejected))
        leads.extend(found[:remaining])
        remaining = max(0, limit - len(leads) - len(rejected))
        rejected.extend(denied[:remaining])
        if len(leads) + len(rejected) >= limit:
            return leads, rejected
    return leads, rejected


def lead_priority(lead: dict[str, str]) -> int:
    """Rank limited fetch slots, never classify a lead as an accepted specimen."""
    url = unquote(lead["url"]).lower()
    words = r"licen[cs]e|identification|specimen|sample|real.?id|passport|resident|employment|card"
    score = sum(
        weight
        for key, weight in (
            ("alt", 5),
            ("caption", 3),
            ("table_row_context", 3),
            ("heading", 2),
            ("context", 1),
        )
        if re.search(words, lead.get(key, ""), re.I)
    )
    if lead.get("table_row_context") and re.search(words, lead["table_row_context"], re.I):
        score += 6
    if re.search(words, url, re.I):
        score += 4
    if lead.get("element") == "a" and "/media/" in url:
        score += 2
    if re.search(r"logo|icon[-_]|flag[-_]|[-_]flag|favicon", url):
        score -= 20
    return score
