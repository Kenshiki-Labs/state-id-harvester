"""Import explicitly acquired browser originals with byte and parent-HTML binding."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from .network import FetchError, official_url, publisher_jurisdiction
from .paths import contained_path
from .seeds import COLLECTION_DOMAINS

if TYPE_CHECKING:
    from .gallery import GalleryJob


def bounded_file(root: Path, name: str, limit: int) -> bytes:
    path = contained_path(root, name)
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Browser evidence exceeds byte budget")
    return data


def import_page(
    job: GalleryJob, path: Path
) -> tuple[dict[str, Any], dict[str, dict[str, str]], str]:
    from .gallery import sha

    value = json.loads(bounded_file(path.parent, path.name, 2_000_000))
    source_url = official_url(value["source_page_url"])
    collection = value.get("collection") or publisher_jurisdiction(
        urlsplit(source_url).hostname or ""
    )
    if collection not in COLLECTION_DOMAINS:
        raise ValueError("Unknown gallery source collection")
    html = bounded_file(
        path.parent, value["html_path"], min(job.options.max_html_bytes, job.remaining)
    )
    if sha(html) != value["parent_html_sha256"]:
        raise ValueError("Parent HTML hash mismatch")
    job.remaining -= len(html)
    leads = job.page(
        collection,
        html,
        source_url,
        "browser_import:" + str(value.get("html_acquisition_method", "unspecified")),
    )
    if not isinstance(value.get("images"), list) or len(value["images"]) > 2000:
        raise ValueError("Invalid browser image ledger")
    return value, {lead["url"]: lead for lead in leads}, collection


async def import_image(
    job: GalleryJob,
    root: Path,
    record: dict[str, Any],
    leads: dict[str, dict[str, str]],
    collection: str,
) -> None:
    from .gallery import sha

    url = official_url(record["url"])
    final_url = official_url(record["asset_url"])
    if url not in leads or record.get("altered") is not False:
        raise ValueError("Browser image is not bound to observed parent HTML or is altered")
    data = bounded_file(root, record["path"], min(job.options.max_image_bytes, job.remaining))
    job.remaining -= len(data)
    if sha(data) != record["sha256"] or len(data) != record["size_bytes"]:
        raise ValueError("Browser image integrity mismatch")
    headers = {key.lower(): value for key, value in record.get("headers", {}).items()}
    lead = {
        **leads[url],
        "collection": collection,
        "browser_caption": str(record.get("caption", ""))[:6000],
        "browser_design_label": str(record.get("design_label", ""))[:6000],
        "usage_constraints": str(record.get("usage_constraints", ""))[:6000],
    }
    await job.asset(
        lead,
        data,
        final_url,
        headers.get("content-type", ""),
        "browser_assisted_import; network_not_replayed",
    )


async def import_browser_manifest(job: GalleryJob, path: Path) -> None:
    try:
        value, leads, collection = import_page(job, path)
    except (ValueError, OSError, KeyError, TypeError, FetchError) as exc:
        job.event("", str(path), "failed", "browser_manifest:" + type(exc).__name__)
        return
    for record in value["images"]:
        if job.requested_assets >= job.options.max_assets:
            job.event(collection, "", "skipped", "Browser import asset budget exhausted")
            return
        job.requested_assets += 1
        try:
            await import_image(job, path.parent, record, leads, collection)
        except (ValueError, OSError, KeyError, TypeError, AttributeError, FetchError) as exc:
            job.event(
                collection,
                str(record.get("url", "")) if isinstance(record, dict) else "",
                "failed",
                "browser_image:" + type(exc).__name__,
            )
