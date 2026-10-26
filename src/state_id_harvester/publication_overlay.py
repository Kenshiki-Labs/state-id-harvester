"""Merge reviewed publication metadata without promoting reference images to cohorts."""

from __future__ import annotations

import copy
import ipaddress
import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import parse_qsl, unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

HASH = r"^[a-f0-9]{64}$"


def _contains_contact(value: str) -> bool:
    """Inspect disjoint address segments without an unanchored repeating regex."""
    segments = value.split("@")
    for local, following in zip(segments, segments[1:], strict=False):
        if not local or re.fullmatch(r"[\w.+-]", local[-1]) is None:
            continue
        domain = re.match(r"[\w.-]+", following)
        if domain is not None and _domain_has_suffix(domain.group()):
            return True
    return False


def _domain_has_suffix(domain: str) -> bool:
    return any(
        character == "."
        and index > 0
        and re.fullmatch(r"[a-z]{2}", domain[index + 1 : index + 3], re.I)
        for index, character in enumerate(domain)
    )


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OverlayCitation(Metadata):
    title: str = Field(min_length=1, max_length=240, pattern=r"^[^\x00-\x1f<>]+$")
    url: str = Field(max_length=4096)
    sha256: str = Field(pattern=HASH)
    retrieved_at: str = Field(max_length=64)
    publisher_host: str = Field(min_length=1, max_length=253)
    publisher_jurisdiction: str | None
    discovery_jurisdiction: str
    credential_format: Literal["ID1"]
    relevance: Literal["candidate", "quarantined"]
    review_status: Literal["unreviewed", "rejected"]
    page_count: int = Field(ge=0)

    @field_validator("url")
    @classmethod
    def public_https(cls, value: str) -> str:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username
            or parsed.password
            or parsed.fragment
            or any(ord(c) < 33 for c in value)
            or "\\" in value
            or host == "localhost"
            or host.endswith((".local", ".localhost", ".internal"))
        ):
            raise ValueError("Public citation requires credential-free public HTTPS")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("Private network citation is not publishable")
        sensitive = re.compile(
            r"token|secret|password|credential|api.?key|claim|email|social.?security", re.I
        )
        if any(
            sensitive.search(key) or key.lower() in {"key", "authorization", "ssn"}
            for key, _ in parse_qsl(parsed.query)
        ):
            raise ValueError("Private citation query parameters are not publishable")
        if re.search(r"/(?:Users|private|home)/|file:", unquote(parsed.path), re.I):
            raise ValueError("Private file path is not publishable")
        return value

    @field_validator("title")
    @classmethod
    def metadata_label(cls, value: str) -> str:
        if _contains_contact(value) or re.search(r"/(?:Users|private|home)/", value, re.I):
            raise ValueError("Personal contact or local path is not a publication title")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def retrieval_timestamp(cls, value: str) -> str:
        if value:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if "T" not in value or parsed.tzinfo is None:
                raise ValueError("Retrieval timestamp requires a timezone")
        return value


class OverlayReference(Metadata):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,150}$")
    source_sha256: str = Field(pattern=HASH)
    asset_sha256: str = Field(pattern=HASH)
    original_asset_sha256: str = Field(pattern=HASH)
    kind: Literal["native_image", "direct_image", "page_plate"]
    page_number: int | None = Field(ge=1)


class OverlayCollection(Metadata):
    code: str
    citations: list[OverlayCitation] = Field(max_length=10000)
    references: list[OverlayReference] = Field(max_length=10000)


class PublicationOverlay(Metadata):
    schema_version: Literal[1]
    collections: list[OverlayCollection] = Field(max_length=51)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("Publication overlay requires integer schema version 1")
        return value


def _validate_citations(collection: OverlayCollection, states: set[str]) -> set[str]:
    hashes: set[str] = set()
    citations: dict[tuple[str, str], OverlayCitation] = {}
    for item in collection.citations:
        if (
            item.discovery_jurisdiction != collection.code
            or item.publisher_jurisdiction not in states | {None, "US_FED"}
            or item.publisher_host != urlsplit(item.url).hostname
        ):
            raise ValueError("Citation jurisdiction or publisher does not match")
        identity = (item.sha256, item.url)
        if identity in citations and citations[identity] != item:
            raise ValueError("Conflicting duplicate citation")
        citations[identity] = item
        hashes.add(item.sha256)
    return hashes


def _validate_references(references: list[OverlayReference], hashes: set[str]) -> None:
    identities: dict[str, OverlayReference] = {}
    for reference in references:
        if reference.source_sha256 not in hashes:
            raise ValueError("Orphan publication reference")
        if reference.id in identities and identities[reference.id] != reference:
            raise ValueError("Conflicting duplicate reference")
        identities[reference.id] = reference


def _validate_collections(overlay: PublicationOverlay, states: set[str]) -> None:
    codes: set[str] = set()
    for collection in overlay.collections:
        if collection.code not in states or collection.code in codes:
            raise ValueError("Unknown or duplicate publication collection")
        codes.add(collection.code)
        hashes = _validate_citations(collection, states)
        _validate_references(collection.references, hashes)


def _merge_citation(item: OverlayCitation, old: dict[str, Any] | None) -> dict[str, Any]:
    incoming = item.model_dump()
    if old is not None:
        if old.get("retrieved_at") and not incoming["retrieved_at"]:
            incoming["retrieved_at"] = old["retrieved_at"]
        # A publication overlay cannot erase an existing accepted source review.
        if old.get("review_status") == "accepted":
            incoming["review_status"] = "accepted"
    return incoming


def _reference_counts(
    references: list[OverlayReference], baseline_hashes: set[str]
) -> tuple[int, int]:
    native = set()
    plates = set()
    for reference in references:
        if reference.source_sha256 in baseline_hashes:
            continue
        if reference.kind == "native_image":
            native.add((reference.source_sha256, reference.original_asset_sha256))
        elif reference.kind == "page_plate":
            plates.add(
                (reference.source_sha256, reference.page_number or reference.original_asset_sha256)
            )
    return len(native), len(plates)


def _merge_row(row: dict[str, Any], collection: OverlayCollection) -> None:
    baseline_hashes = {item["sha256"] for item in row["sources"]}
    sources = {(item["sha256"], item["url"]): item for item in row["sources"]}
    for item in collection.citations:
        identity = (item.sha256, item.url)
        sources[identity] = _merge_citation(item, sources.get(identity))
    row["sources"] = list(sources.values())
    row["counts"]["sources"] = len(row["sources"])
    row["counts"]["relevant_sources"] = sum(
        item["relevance"] == "candidate" for item in row["sources"]
    )
    native, plates = _reference_counts(collection.references, baseline_hashes)
    row["counts"]["embedded_images"] += native
    row["counts"]["rendered_pages"] += plates
    row["status"] = "sources_available" if row["sources"] else "gap"


def merge_overlay(
    catalog: dict[str, Any], overlay: object, known_states: set[str]
) -> dict[str, Any]:
    """Validate everything before producing an independent, idempotent merged catalog."""
    parsed = PublicationOverlay.model_validate(overlay)
    _validate_collections(parsed, known_states)
    result = copy.deepcopy(catalog)
    rows = {row["code"]: row for row in result["jurisdictions"]}
    if set(rows) != known_states or len(result["jurisdictions"]) != len(known_states):
        raise ValueError("Baseline must retain all 51 state and DC rows")
    for collection in parsed.collections:
        _merge_row(rows[collection.code], collection)
    for row in rows.values():
        row["counts"]["sources"] = len(row["sources"])
        row["counts"]["relevant_sources"] = sum(
            item["relevance"] == "candidate" for item in row["sources"]
        )
    counts = result["jurisdictions"][0]["counts"].keys()
    result["stats"] = {
        "jurisdictions": len(rows),
        "jurisdictions_with_sources": sum(bool(row["sources"]) for row in rows.values()),
        "jurisdictions_with_accepted_cohorts": sum(
            bool(row["counts"]["accepted_cohorts"]) for row in rows.values()
        ),
        **{key: sum(row["counts"][key] for row in rows.values()) for key in counts},
    }
    return result
