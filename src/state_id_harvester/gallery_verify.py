"""Offline verification of private gallery bytes and their HTML evidence graph."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .gallery_html import discover_images
from .gallery_raster import raster_header
from .network import FetchError, official_url
from .paths import contained_path
from .seeds import COLLECTION_DOMAINS

MAX_MANIFEST_BYTES = 32_000_000
MAX_RECORDS = 100_000


def load_gallery_manifest(root: Path) -> dict[str, Any]:
    path = contained_path(root, "manifest.json")
    with path.open("rb") as stream:
        data = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError("Gallery receipt exceeds byte budget")
    value: Any = json.loads(data)
    return validate_manifest(value)


def validate_manifest(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("track") != "html_gallery"
        or value.get("schema_version") != 1
    ):
        raise ValueError("Not a gallery receipt")
    if value.get("accepted_cohorts") != 0:
        raise ValueError("Gallery receipt cannot establish accepted cohorts")
    run_id = value.get("run_id")
    if not isinstance(run_id, str):
        raise ValueError("Invalid gallery run identifier")
    uuid.UUID(run_id)
    valid_timestamp(value["started_at"])
    for section in ("assets", "pages", "aliases"):
        if not isinstance(value.get(section), list) or len(value[section]) > MAX_RECORDS:
            raise ValueError("Malformed gallery inventory section")
    return value


def valid_timestamp(value: Any) -> None:
    if not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None:
        raise ValueError("Invalid gallery observation timestamp")


def checksum(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError("Invalid SHA256")
    return value


def record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("review_status") != "unreviewed":
        raise ValueError("Gallery observations must remain unreviewed")
    for field in ("retrieved_at", "first_seen_at", "last_seen_at"):
        if field in value:
            valid_timestamp(value[field])
    return value


def collection(value: Any) -> str:
    if not isinstance(value, str) or value not in COLLECTION_DOMAINS:
        raise ValueError("Invalid gallery collection")
    return value


def verified_file(root: Path, item: dict[str, Any], expected_path: str, limit: int) -> bytes:
    if item.get("path") != expected_path or type(item.get("size_bytes")) is not int:
        raise ValueError("Invalid canonical gallery object path or size")
    expected_size = item["size_bytes"]
    if not 0 < expected_size <= limit:
        raise ValueError("Gallery object size exceeds policy")
    hasher = hashlib.sha256()
    prefix = bytearray()
    size = 0
    with contained_path(root, expected_path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            size += len(chunk)
            if size > expected_size:
                raise ValueError("Gallery object grew beyond receipt size")
            hasher.update(chunk)
            if len(prefix) < 65536:
                prefix.extend(chunk[: 65536 - len(prefix)])
    if size != expected_size or hasher.hexdigest() != checksum(item.get("sha256")):
        raise ValueError("Gallery object integrity mismatch")
    return bytes(prefix)


def verify_asset(root: Path, value: Any) -> dict[str, Any]:
    item = record(value)
    sha = checksum(item.get("sha256"))
    image_format = item.get("format")
    if (
        image_format not in {"png", "jpeg"}
        or item.get("altered") is not False
        or item.get("accepted_cohort") is not False
        or item.get("plate_composition") != "unreviewed"
    ):
        raise ValueError("Invalid gallery original interpretation")
    media = item.get("content_type")
    expected_media = "image/png" if image_format == "png" else "image/jpeg"
    if not isinstance(media, str) or media.partition(";")[0].strip().lower() not in {
        expected_media,
        "application/octet-stream",
    }:
        raise ValueError("Invalid gallery original Content-Type")
    if type(item.get("width")) is not int or type(item.get("height")) is not int:
        raise ValueError("Invalid gallery pixel dimensions")
    header = verified_file(root, item, f"originals/{sha}.{image_format}", 30_000_000)
    detected, width, height = raster_header(header)
    if detected != image_format or width != item.get("width") or height != item.get("height"):
        raise ValueError("Gallery raster dimensions disagree with receipt")
    if min(width, height) < 1 or max(width, height) > 20000 or width * height > 40_000_000:
        raise ValueError("Gallery raster exceeds validation pixel policy")
    return item


def verify_page(root: Path, value: Any) -> tuple[str, str, str]:
    item = record(value)
    valid_timestamp(item["retrieved_at"])
    sha = checksum(item.get("sha256"))
    verified_file(root, item, f"html/{sha}.html", 5_000_000)
    return collection(item.get("collection")), official_url(item["url"]), sha


def verify_alias(
    value: Any, assets: set[str], pages: set[tuple[str, str, str]]
) -> tuple[str, str, str]:
    item = record(value)
    valid_timestamp(item["retrieved_at"])
    asset = checksum(item.get("asset_sha256"))
    parent = checksum(item.get("parent_html_sha256"))
    binding = collection(item.get("collection")), official_url(item["source_page_url"]), parent
    official_url(item["url"])
    official_url(item["final_url"])
    if (
        asset not in assets
        or binding not in pages
        or item.get("parent_html_path") != f"html/{parent}.html"
    ):
        raise ValueError("Dangling gallery asset or parent HTML binding")
    return binding


def verify_parent_links(
    root: Path, binding: tuple[str, str, str], aliases: list[dict[str, Any]]
) -> None:
    _, page_url, sha = binding
    with contained_path(root, f"html/{sha}.html").open("rb") as stream:
        data = stream.read(5_000_001)
    if len(data) > 5_000_000 or hashlib.sha256(data).hexdigest() != sha:
        raise ValueError("Parent HTML changed during evidence verification")
    leads, _ = discover_images(data, page_url, 1000)
    observed = {lead["url"] for lead in leads}
    if any(alias["url"] not in observed for alias in aliases):
        raise ValueError("Gallery URL is absent from retained parent HTML")


def verify_gallery(root: Path, manifest: dict[str, Any] | None = None) -> list[str]:
    """Return bounded, authored errors; never fetch URLs or approve a credential."""
    try:
        data = validate_manifest(manifest) if manifest is not None else load_gallery_manifest(root)
        return verify_inventory(root, data)
    except (ValueError, OSError, KeyError, TypeError, FetchError) as exc:
        return [f"manifest:{type(exc).__name__}"]


def verify_inventory(root: Path, data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    assets: set[str] = set()
    pages: set[tuple[str, str, str]] = set()
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for index, item in enumerate(data["assets"]):
        try:
            verified = verify_asset(root, item)
            assets.add(verified["sha256"])
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append(f"asset[{index}]:{type(exc).__name__}")
    for index, item in enumerate(data["pages"]):
        try:
            pages.add(verify_page(root, item))
        except (ValueError, OSError, KeyError, TypeError, FetchError) as exc:
            errors.append(f"page[{index}]:{type(exc).__name__}")
    for index, item in enumerate(data["aliases"]):
        try:
            binding = verify_alias(item, assets, pages)
            groups.setdefault(binding, []).append(item)
        except (ValueError, OSError, KeyError, TypeError, FetchError) as exc:
            errors.append(f"alias[{index}]:{type(exc).__name__}")
    for binding, aliases in groups.items():
        try:
            verify_parent_links(root, binding, aliases)
        except (ValueError, OSError, KeyError, TypeError, FetchError) as exc:
            errors.append(f"parent_links:{type(exc).__name__}")
    return errors
