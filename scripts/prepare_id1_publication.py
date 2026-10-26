"""Prepare marked ID-1 delivery copies, then upload blobs without publishing any index."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vault_sync import CHUNK_BYTES, Vault, marked_reference, specimen_records  # noqa: E402

from state_id_harvester.gallery_raster import raster_header  # noqa: E402
from state_id_harvester.paths import contained_path, managed_path  # noqa: E402

HASH = re.compile(r"[a-f0-9]{64}")
MAX_JSON = 8 * 1024 * 1024
MAX_CANONICAL_BYTES = 50 * 1024 * 1024
BOUNDARY_BASES = {"visual_native_extent", "visual_card_corners"}
INDEX_NAME = "index.json"
UPLOAD_RECEIPT_NAME = "upload-receipt.json"
DIMENSIONS = {(4280, 2699), (2699, 4280)}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_metadata(path: Path) -> tuple[bytes, dict[str, Any]]:
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON + 1)
    if len(raw) > MAX_JSON:
        raise ValueError("Metadata exceeds byte budget")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Expected metadata object")
    return raw, value


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def read_canonical(source: Path, relative: str) -> bytes:
    path = contained_path(source, relative)
    if path.stat().st_size > MAX_CANONICAL_BYTES:
        raise ValueError("Canonical artifact exceeds byte budget")
    with path.open("rb") as stream:
        raw = stream.read(MAX_CANONICAL_BYTES + 1)
    if len(raw) > MAX_CANONICAL_BYTES:
        raise ValueError("Canonical artifact exceeds byte budget")
    return raw


def validate_canonical(source: Path, row: dict[str, Any], parent: dict[str, Any]) -> None:
    if (
        row["source_sha256"] != parent["source_sha256"]
        or row["original_reference_sha256"] != parent["asset_sha256"]
    ):
        raise ValueError("Normalized source or parent lineage mismatch")
    if row["status"] != "normalized_reference" or row["boundary_basis"] not in BOUNDARY_BASES:
        raise ValueError("Reference is not admitted by normalization gate")
    dimensions = (row["width_px"], row["height_px"])
    if any(type(value) is not int for value in dimensions) or dimensions not in DIMENSIONS:
        raise ValueError("Canonical dimensions must be exact ID-1 pixel dimensions")
    digest = row["asset_sha256"]
    if not HASH.fullmatch(digest) or row["path"] != f"{digest}.png":
        raise ValueError("Canonical path must match content hash")
    raw = read_canonical(source, row["path"])
    if sha(raw) != digest:
        raise ValueError("Canonical artifact checksum mismatch")
    kind, width, height = raster_header(raw)
    if kind != "png" or (width, height) != dimensions:
        raise ValueError("Canonical raster header mismatch")


def validate_results(source: Path, manifest: dict[str, Any], old: dict[str, Any]) -> list[dict]:
    originals = {(item["state"], item["id"]): item for item in old["specimens"]}
    if len(originals) != len(old["specimens"]):
        raise ValueError("Duplicate original reference identity")
    results = manifest["results"]
    if len(results) != manifest["normalized_references"] or not results:
        raise ValueError("Normalization count mismatch")
    seen = set()
    for row in results:
        identity = (row["state"], row["id"])
        if identity in seen or identity not in originals:
            raise ValueError("Duplicate or unknown normalized reference identity")
        seen.add(identity)
        validate_canonical(source, row, originals[identity])
    return results


def prepare(source: Path, original_index: Path, destination: Path) -> dict[str, Any]:
    source, original_index, destination = map(managed_path, (source, original_index, destination))
    manifest_raw, manifest = read_metadata(contained_path(source, "manifest.json"))
    original_raw, old = read_metadata(original_index)
    specimen_records(original_raw, require_key=True)
    results = validate_results(source, manifest, old)  # Every input before creating any derivative.
    batch_hash = sha(manifest_raw + original_raw)
    destination.mkdir(parents=True, exist_ok=True)
    contained_path(destination, "index-before.json").write_bytes(original_raw)
    images = contained_path(destination, "display")
    images.mkdir(exist_ok=True)
    records, lineage = [], []
    for count, row in enumerate(results, 1):
        raw = read_canonical(source, row["path"])
        if sha(raw) != row["asset_sha256"]:
            raise ValueError("Canonical artifact changed after validation")
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or (image.shape[1], image.shape[0]) != (row["width_px"], row["height_px"]):
            raise ValueError("Canonical image decode mismatch")
        marked = marked_reference(image)
        if marked is None:
            raise ValueError("Marked delivery copy exceeds upload budget")
        delivery, transform = marked
        digest = sha(delivery)
        _, width, height = raster_header(delivery)
        contained_path(images, f"{digest}.png").write_bytes(delivery)
        records.append(
            {
                "id": row["id"],
                "state": row["state"],
                "source_sha256": row["source_sha256"],
                "asset_sha256": digest,
                "review_status": "reference_only",
                "key": f"specimens/id1/{batch_hash}/{digest}.png",
                "original_reference_sha256": row["original_reference_sha256"],
                "canonical_asset_sha256": row["asset_sha256"],
                "width_px": row["width_px"],
                "height_px": row["height_px"],
                "boundary_basis": row["boundary_basis"],
            }
        )
        lineage.append(
            {
                "id": row["id"],
                "state": row["state"],
                "canonical_sha256": row["asset_sha256"],
                "canonical_width_px": row["width_px"],
                "canonical_height_px": row["height_px"],
                "delivery_sha256": digest,
                "delivery_transform": transform,
                "delivery_size_bytes": len(delivery),
                "delivery_width_px": width,
                "delivery_height_px": height,
                "canonical_resampling_calls": 0,
                "delivery_resampling_calls": 1,
            }
        )
        if count % 25 == 0:
            print(f"Prepared {count}/{len(results)} delivery images", flush=True)
    result = {"specimens": records}
    write_json(contained_path(destination, INDEX_NAME), result)
    write_json(
        contained_path(destination, "preparation-receipt.json"),
        {
            "prepared_at": datetime.now(UTC).isoformat(),
            "batch_sha256": batch_hash,
            "normalization_manifest_sha256": sha(manifest_raw),
            "original_index_sha256": sha(original_raw),
            "index_sha256": sha(contained_path(destination, "index.json").read_bytes()),
            "original_reference_count": len(old["specimens"]),
            "prepared_reference_count": len(records),
            "originals_and_canonical_unchanged": True,
            "lineage": lineage,
        },
    )
    return result


class PacedVault(Vault):
    """All authenticated requests, including verification reads, remain under120/minute."""

    def __init__(self, origin: str, key: str) -> None:
        super().__init__(origin, key)
        self.last_request = 0.0
        self.request_lock = Lock()

    def pace(self) -> None:
        with self.request_lock:
            time.sleep(max(0.0, 0.7 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()

    def put(self, key: str, data: bytes, **kwargs: Any) -> None:
        for attempt in range(4):
            self.pace()
            try:
                super().put(key, data, **kwargs)
                return
            except RuntimeError as error:
                if attempt == 3 or not any(code in str(error) for code in ("HTTP 429", "HTTP 503")):
                    raise
                time.sleep(2 ** (attempt + 1))

    def get(self, key: str, **kwargs: Any) -> bytes | None:
        for attempt in range(4):
            self.pace()
            try:
                return super().get(key, **kwargs)
            except RuntimeError as error:
                if attempt == 3 or not any(code in str(error) for code in ("HTTP 429", "HTTP 503")):
                    raise
                time.sleep(2 ** (attempt + 1))
        raise RuntimeError("Verification download retry exhausted")


def transfer_blob(destination: Path, vault: Vault, row: dict[str, Any]) -> dict[str, Any]:
    raw = contained_path(destination, Path("display") / f"{row['asset_sha256']}.png").read_bytes()
    if sha(raw) != row["asset_sha256"]:
        raise ValueError("Prepared display changed after validation")
    vault.put(row["key"], raw, specimen=True, source_sha256=row["source_sha256"])
    returned = vault.get(row["key"])
    if returned is None or sha(returned) != row["asset_sha256"]:
        raise ValueError("Uploaded display readback mismatch")
    return {
        "id": row["id"],
        "state": row["state"],
        "key": row["key"],
        "asset_sha256": row["asset_sha256"],
        "size_bytes": len(raw),
    }


def upload_blobs(destination: Path, vault: Vault) -> dict[str, Any]:
    destination = managed_path(destination)
    _, index = read_metadata(contained_path(destination, INDEX_NAME))
    _, receipt = read_metadata(contained_path(destination, "preparation-receipt.json"))
    if sha(contained_path(destination, INDEX_NAME).read_bytes()) != receipt["index_sha256"]:
        raise ValueError("Prepared index changed")
    # Prevalidate all blobs and immutable keys before the first network mutation.
    batch_hash = receipt["batch_sha256"]
    for row in index["specimens"]:
        digest = row["asset_sha256"]
        if not HASH.fullmatch(digest) or row["key"] != f"specimens/id1/{batch_hash}/{digest}.png":
            raise ValueError("Invalid immutable display object key")
        raw = contained_path(destination, Path("display") / f"{digest}.png").read_bytes()
        if sha(raw) != digest or len(raw) > CHUNK_BYTES:
            raise ValueError("Prepared display checksum mismatch")
    verified = []
    receipt_path = contained_path(destination, UPLOAD_RECEIPT_NAME)
    if receipt_path.exists():
        _, prior = read_metadata(receipt_path)
        if prior["index_sha256"] != receipt["index_sha256"]:
            raise ValueError("Upload receipt belongs to another index")
        verified = prior["verified"]
    completed = {(row["state"], row["id"], row["asset_sha256"]) for row in verified}
    upload_receipt = {
        "index_sha256": receipt["index_sha256"],
        "pointer_published": False,
        "verified": verified,
    }
    pending = [
        row
        for row in index["specimens"]
        if (row["state"], row["id"], row["asset_sha256"]) not in completed
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(transfer_blob, destination, vault, row) for row in pending]
        for future in as_completed(futures):
            verified.append(future.result())
            write_json(contained_path(destination, UPLOAD_RECEIPT_NAME), upload_receipt)
            if len(verified) % 20 == 0:
                print(
                    f"Uploaded and hash-verified {len(verified)}/{len(index['specimens'])}",
                    flush=True,
                )
    upload_receipt["completed_at"] = datetime.now(UTC).isoformat()
    write_json(contained_path(destination, UPLOAD_RECEIPT_NAME), upload_receipt)
    return upload_receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path("output/id1-normalization/easy-pass-01")
    )
    parser.add_argument("--original-index", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=Path("output/id1-publication"))
    parser.add_argument("--upload-only", action="store_true")
    args = parser.parse_args()
    if not args.upload_only:
        prepare(args.source, args.original_index, args.destination)
        return
    vault = PacedVault(
        "https://cadastre.kenshikilabs.com",
        Path(".private/cadastre-ingest.key").read_text().strip(),
    )
    try:
        upload_blobs(args.destination, vault)
    finally:
        vault.close()


if __name__ == "__main__":
    main()
