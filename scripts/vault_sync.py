"""Private snapshot transport and visibly marked reference derivatives.

Nothing in this module writes to a public tree or a GitHub release. Authentication
is read from CADASTRE_INGEST_KEY and is never included in diagnostics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import struct
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from state_id_harvester.paths import contained_path, managed_path
from state_id_harvester.snapshots import restore_library

CHUNK_BYTES = 40 * 1024 * 1024
INDEX_LIMIT = 4 * 1024 * 1024
HEX_SHA256 = re.compile(r"[a-f0-9]{64}")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_key(key: str) -> str:
    if (
        not re.fullmatch(r"(?:snapshots|specimens|indexes)/[A-Za-z0-9_./-]+", key)
        or any(p in {"", ".", ".."} for p in key.split("/"))
        or len(key) > 1024
    ):
        raise ValueError("Invalid private vault key")
    return key


class Vault:
    def __init__(self, base_url: str, key: str) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Vault base URL must be an HTTPS origin")
        if not key:
            raise ValueError("CADASTRE_INGEST_KEY is required")
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {key}"},
            timeout=httpx.Timeout(180, connect=30),
            follow_redirects=False,
        )

    def close(self) -> None:
        self.client.close()

    def put(
        self, key: str, data: bytes, *, specimen: bool = False, source_sha256: str | None = None
    ) -> None:
        if len(data) > CHUNK_BYTES:
            raise ValueError("Private upload exceeds the 40 MiB transport budget")
        headers = {
            "x-content-sha256": hashlib.sha256(data).hexdigest(),
            "content-type": "image/png" if specimen else "application/octet-stream",
        }
        if specimen:
            if source_sha256 is None or not HEX_SHA256.fullmatch(source_sha256):
                raise ValueError("Prepared specimens require source SHA-256 lineage")
            headers["x-cadastre-reference-only"] = "true"
            headers["x-cadastre-source-sha256"] = source_sha256
        response = self.client.put(
            f"{self.base_url}/internal/objects/{safe_key(key)}",
            content=data,
            headers=headers,
        )
        # Avoid printing server bodies, URLs or headers containing privileged information.
        if response.status_code not in {200, 201, 204}:
            raise RuntimeError(f"Private vault upload failed (HTTP {response.status_code})")

    def get(self, key: str, *, limit: int = CHUNK_BYTES, missing_ok: bool = False) -> bytes | None:
        with self.client.stream(
            "GET", f"{self.base_url}/internal/objects/{safe_key(key)}"
        ) as response:
            if missing_ok and response.status_code == 404:
                return None
            if response.status_code != 200:
                raise RuntimeError(f"Private vault download failed (HTTP {response.status_code})")
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > limit:
                    raise ValueError("Private download exceeds its byte budget")
            return bytes(body)


def push_snapshot(vault: Vault, directory: Path, *, chunk_bytes: int = CHUNK_BYTES) -> None:
    if not 0 < chunk_bytes <= CHUNK_BYTES:
        raise ValueError("Snapshot chunk size exceeds transport budget")
    archives = json.loads((directory / "library-index.json").read_text())
    if not isinstance(archives, list) or not archives:
        raise ValueError("Snapshot archive index must be a nonempty list")
    prefix = f"snapshots/{secrets.token_hex(20)}"
    result = []
    for archive in archives:
        name = archive["name"]
        if not re.fullmatch(r"library-\d{3,}\.tar\.gz", name, flags=re.ASCII):
            raise ValueError("Invalid snapshot archive name")
        path = directory / name
        if digest(path) != archive["sha256"] or path.stat().st_size != archive["size_bytes"]:
            raise ValueError("Snapshot archive integrity check failed")
        chunks = []
        with path.open("rb") as stream:
            while data := stream.read(chunk_bytes):
                key = f"{prefix}/{name}.part-{len(chunks):05}"
                vault.put(key, data)
                chunks.append(
                    {
                        "key": key,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "size_bytes": len(data),
                    }
                )
        result.append({**archive, "chunks": chunks})
    index = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "archives": result,
    }
    encoded = (json.dumps(index, indent=2) + "\n").encode()
    if len(encoded) > INDEX_LIMIT:
        raise ValueError("Snapshot index exceeds budget")
    # The pointer becomes visible only after every immutable chunk has uploaded.
    vault.put(f"{prefix}/snapshot-index.json", encoded)
    vault.put("indexes/latest-snapshot.json", encoded)
    print(
        f"Private snapshot uploaded: {len(archives)} archives, "
        f"{sum(len(a['chunks']) for a in result)} chunks"
    )


def restore_archive(vault: Vault, directory: Path, archive: dict) -> None:
    path = directory / archive["name"]
    try:
        remaining = archive["size_bytes"]
        with path.open("wb") as target:
            for chunk in archive["chunks"]:
                data = checked_chunk(vault, chunk, remaining)
                target.write(data)
                remaining -= len(data)
        if remaining or digest(path) != archive["sha256"]:
            raise ValueError("Reassembled archive integrity check failed")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def checked_chunk(vault: Vault, chunk: dict, remaining: int) -> bytes:
    if not 0 < chunk["size_bytes"] <= min(CHUNK_BYTES, remaining):
        raise ValueError("Invalid snapshot chunk size")
    data = vault.get(chunk["key"], limit=chunk["size_bytes"])
    if (
        data is None
        or len(data) != chunk["size_bytes"]
        or hashlib.sha256(data).hexdigest() != chunk["sha256"]
    ):
        raise ValueError("Snapshot chunk integrity check failed")
    return data


def validate_snapshot_index(encoded: bytes) -> list[dict]:
    index = json.loads(encoded)
    if index.get("schema_version") != 1 or not isinstance(index.get("archives"), list):
        raise ValueError("Invalid private snapshot index")
    total_budget = 30 * 1024 * 1024 * 1024
    for archive in index["archives"]:
        if not re.fullmatch(r"library-\d{3,}\.tar\.gz", archive["name"], flags=re.ASCII):
            raise ValueError("Invalid snapshot archive name")
        if (
            not HEX_SHA256.fullmatch(archive["sha256"])
            or not 0 < archive["size_bytes"] <= total_budget
        ):
            raise ValueError("Invalid snapshot archive bounds")
        total_budget -= archive["size_bytes"]
    return index["archives"]


def pull_snapshot(vault: Vault, directory: Path, output: Path, *, missing_ok: bool = False) -> None:
    encoded = vault.get("indexes/latest-snapshot.json", limit=INDEX_LIMIT, missing_ok=missing_ok)
    if encoded is None:
        print("No prior private snapshot; starting an empty collection")
        return
    parts = validate_snapshot_index(encoded)
    directory.mkdir(parents=True, exist_ok=True)
    archives = []
    for archive in parts:
        restore_archive(vault, directory, archive)
        archives.append({key: archive[key] for key in ("name", "sha256", "size_bytes")})
    (directory / "library-index.json").write_text(json.dumps(archives, indent=2) + "\n")
    restore_library(managed_path(directory), managed_path(output))
    print(f"Restored {len(archives)} verified private archives")


def marked_reference(image) -> tuple[bytes, dict] | None:
    import cv2
    import numpy as np

    height, width = image.shape[:2]
    scale = min(1, 2400 / max(height, width))
    rendered = (
        cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
        if scale < 1
        else image
    )
    h, w = rendered.shape[:2]
    canvas = np.full((h + 110, max(w, 900), 3), 255, dtype=np.uint8)
    offset = (canvas.shape[1] - w) // 2
    canvas[:h, offset : offset + w] = rendered
    cv2.rectangle(canvas, (0, h), (canvas.shape[1] - 1, h + 109), (20, 20, 25), -1)
    cv2.putText(
        canvas,
        "SPECIMEN / VERIFICATION REFERENCE ONLY",
        (20, h + 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        "UNREVIEWED REFERENCE - SOURCE GEOMETRY IS NOT PHYSICAL CALIBRATION",
        (20, h + 79),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.54,
        (220, 220, 220),
        1,
        cv2.LINE_AA,
    )
    ok, encoded = cv2.imencode(".png", canvas)
    if not ok or len(encoded) > CHUNK_BYTES:
        return None
    return encoded.tobytes(), {
        "source_width_px": width,
        "source_height_px": height,
        "scale_x": w / width,
        "scale_y": h / height,
        "offset_x_px": offset,
        "offset_y_px": 0,
        "footer_height_px": 110,
    }


def read_candidate_image(source: Path, asset):
    import cv2
    import numpy as np

    source = managed_path(source)
    unresolved = source / asset.path
    if unresolved.is_symlink():
        raise ValueError("Specimen source must not be a symlink")
    path = contained_path(source, asset.path)
    if (
        path.is_symlink()
        or not path.resolve().is_relative_to(source.resolve())
        or not path.is_file()
    ):
        raise ValueError("Specimen path escapes private source tree")
    if path.stat().st_size > 50_000_000:
        raise ValueError("Specimen source exceeds byte budget")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != asset.sha256:
        raise ValueError("Specimen source integrity check failed")
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("Specimen candidates must be PNG images")
    width, height = struct.unpack(">II", data[16:24])
    if not 0 < width * height <= 40_000_000:
        raise ValueError("Specimen source exceeds pixel budget")
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None
    if image.shape[0] * image.shape[1] > 40_000_000:
        return None
    return image


def candidate_assets(
    manifest, *, kinds: frozenset[str] = frozenset({"card_candidate"}), relevant_only: bool = True
):
    for document in manifest.documents:
        if relevant_only and document.relevance != "candidate":
            continue
        for asset in document.assets:
            if asset.kind in kinds:
                yield document, asset


def prepare_specimen(source: Path, destination: Path, document, asset) -> dict | None:
    image = read_candidate_image(source, asset)
    if image is None:
        return None
    marked = marked_reference(image)
    if marked is None:
        return None
    data, transform = marked
    checksum = hashlib.sha256(data).hexdigest()
    contained_path(managed_path(destination), f"{checksum}.png").write_bytes(data)
    return {
        "id": f"sp_{checksum[:32]}",
        # This is the discovery jurisdiction, never a depicted-state review.
        "state": document.download.source.discovery_jurisdiction,
        "source_sha256": document.download.sha256,
        "asset_sha256": checksum,
        "original_asset_sha256": asset.sha256,
        "page_number": asset.page_number,
        "review_status": "reference_only",
        "depicted_jurisdiction": None,
        "reference_kind": "page_plate" if asset.kind == "page_render" else "crop_candidate",
        "source_collection": document.download.source.discovery_jurisdiction,
        "credential_format": document.download.source.credential_format,
        "source_relevance": document.relevance,
        "transform": transform,
    }


def prepare_collection(source: Path, destination: Path, limit: int, *, federal: bool) -> list[dict]:
    from state_id_harvester.library import read_manifest

    if not 0 <= limit <= 1000:
        raise ValueError("Reference limit must be between 0 and 1000")
    source, destination = managed_path(source), managed_path(destination)
    manifest = read_manifest(source)
    destination.mkdir(parents=True, exist_ok=True)
    items = []
    seen: set[str] = set()
    kinds = frozenset({"page_render"}) if federal else frozenset({"card_candidate"})
    for document, asset in candidate_assets(manifest, kinds=kinds, relevant_only=not federal):
        if len(items) >= limit:
            break
        if asset.sha256 in seen:
            continue
        item = prepare_specimen(source, destination, document, asset)
        if item is not None:
            items.append(item)
            seen.add(asset.sha256)
    return items


def prepare_specimens(
    source: Path, destination: Path, limit: int, *, federal_limit: int = 30
) -> list[dict]:
    from state_id_harvester.library import read_manifest

    source, destination = managed_path(source), managed_path(destination)
    manifest = read_manifest(source)
    primary_federal = manifest.requested_jurisdictions == ["US_FED"]
    primary_limit = federal_limit if primary_federal else limit
    items = prepare_collection(source, destination, primary_limit, federal=primary_federal)
    federal_source = contained_path(source, "federal")
    if not primary_federal and (federal_source / "manifest.json").is_file():
        items.extend(prepare_collection(federal_source, destination, federal_limit, federal=True))
    contained_path(destination, "specimens.json").write_text(
        json.dumps({"specimens": items}, indent=2) + "\n"
    )
    federal_count = sum(item["source_collection"] == "US_FED" for item in items)
    print(
        f"Prepared {len(items)} visibly marked private references "
        f"({federal_count} federal page plates)"
    )
    return items


def push_specimens(vault: Vault, directory: Path) -> None:
    index = json.loads((directory / "specimens.json").read_text())
    prefix = f"specimens/{secrets.token_hex(20)}"
    for item in index["specimens"]:
        checksum = item["asset_sha256"]
        if not HEX_SHA256.fullmatch(checksum) or item["review_status"] != "reference_only":
            raise ValueError("Invalid prepared specimen record")
        path = directory / f"{checksum}.png"
        if path.stat().st_size > CHUNK_BYTES or digest(path) != checksum:
            raise ValueError("Prepared specimen integrity check failed")
        item["key"] = f"{prefix}/{checksum}.png"
        vault.put(
            item["key"], path.read_bytes(), specimen=True, source_sha256=item["source_sha256"]
        )
    vault.put("indexes/specimens.json", (json.dumps(index, indent=2) + "\n").encode())
    print(f"Private reference index uploaded: {len(index['specimens'])} candidates")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", default=os.environ.get("CADASTRE_VAULT_URL", "https://cadastre.kenshikilabs.com")
    )
    commands = parser.add_subparsers(dest="command", required=True)
    push = commands.add_parser("push")
    push.add_argument("archives", type=managed_path)
    pull = commands.add_parser("pull")
    pull.add_argument("output", type=managed_path)
    pull.add_argument("--missing-ok", action="store_true")
    prepare = commands.add_parser("prepare-specimens")
    prepare.add_argument("source", type=managed_path)
    prepare.add_argument("destination", type=managed_path)
    prepare.add_argument("--limit", type=int, default=100)
    prepare.add_argument("--federal-limit", type=int, default=30)
    specimens = commands.add_parser("push-specimens")
    specimens.add_argument("directory", type=managed_path)
    args = parser.parse_args()
    if args.command == "prepare-specimens":
        prepare_specimens(
            args.source, args.destination, args.limit, federal_limit=args.federal_limit
        )
        return
    vault = Vault(args.url, os.environ.get("CADASTRE_INGEST_KEY", ""))
    try:
        if args.command == "push":
            push_snapshot(vault, args.archives)
        elif args.command == "pull":
            with tempfile.TemporaryDirectory(prefix="cadastre-private-") as temporary:
                pull_snapshot(vault, Path(temporary), args.output, missing_ok=args.missing_ok)
        elif args.command == "push-specimens":
            push_specimens(vault, args.directory)
    finally:
        vault.close()


if __name__ == "__main__":
    main()
