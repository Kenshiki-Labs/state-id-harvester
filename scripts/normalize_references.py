"""Repeatable ID-1 derivation gate; original evidence is never modified."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from state_id_harvester.gallery_raster import raster_header
from state_id_harvester.normalization import (
    BoundaryDecision,
    load_rectifier,
    normalize_card,
    read_decisions,
)
from state_id_harvester.paths import managed_path


def bounded_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4_000_000:
        raise ValueError("Invalid or oversized normalization manifest")
    return json.loads(path.read_text())


decisions_from = read_decisions


def decode_original(row: dict) -> tuple[np.ndarray, bytes]:
    unresolved = Path(row["original_path"])
    if unresolved.is_symlink():
        raise ValueError("Original image must not be a symlink")
    path = managed_path(unresolved)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 50_000_000:
        raise ValueError("Invalid original image path or byte budget")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != row["original_asset_sha256"]:
        raise ValueError("Original image integrity mismatch")
    _, width, height = raster_header(data)
    if min(width, height) < 1 or max(width, height) > 20000 or width * height > 40_000_000:
        raise ValueError("Original image exceeds pixel budget")
    image = cv2.imdecode(
        np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION
    )
    if image is None or image.shape != (height, width, 3):
        raise ValueError("Decoded original dimensions disagree with retained header")
    return image, data


def derive_one(row: dict, decision: BoundaryDecision, rectifier, destination: Path) -> dict:
    if decision.original_asset_sha256 != row["original_asset_sha256"]:
        raise ValueError("Boundary decision does not match the original asset")
    image, original = decode_original(row)
    normalized, metadata = normalize_card(image, decision, rectifier)
    ok, encoded = cv2.imencode(".png", normalized, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        raise ValueError("Normalized PNG encoding failed")
    data = encoded.tobytes()
    checksum = hashlib.sha256(data).hexdigest()
    target = destination / f"{checksum}.png"
    target.write_bytes(data)
    decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if not np.array_equal(decoded, normalized):
        raise ValueError("Normalized PNG changed pixel samples")
    if managed_path(row["original_path"]).read_bytes() != original:
        raise ValueError("Original changed during normalization")
    return {
        "state": row["state"],
        "id": row["id"],
        "source_sha256": row["source_sha256"],
        "original_asset_sha256": row["original_asset_sha256"],
        "original_path": row["original_path"],
        "original_reference_sha256": row["asset_sha256"],
        "asset_sha256": checksum,
        "path": target.name,
        "source_width_px": int(image.shape[1]),
        "source_height_px": int(image.shape[0]),
        "decoder": "opencv_bgr_ignore_exif_orientation",
        "color_status": "uncalibrated_display_decode",
        "original_unchanged": True,
        **metadata,
    }


def run(inventory: Path, registry: Path, rectifier_path: Path, output: Path) -> dict:
    output = managed_path(output)
    if output.exists() or output.is_symlink():
        raise ValueError("Normalization output already exists; choose a new run directory")
    inventory_hash = hashlib.sha256(inventory.read_bytes()).hexdigest()
    registry_hash = hashlib.sha256(registry.read_bytes()).hexdigest()
    rows = bounded_json(managed_path(inventory))["rows"]
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("Invalid normalization inventory")
    decisions = decisions_from(managed_path(registry))
    rectifier = load_rectifier(rectifier_path)
    cv2.setNumThreads(1)
    output.parent.mkdir(parents=True, exist_ok=True)
    pending, results = [], []
    with tempfile.TemporaryDirectory(prefix=".id1-stage-", dir=output.parent) as temporary:
        stage = Path(temporary)
        for row in rows:
            decision = decisions.get(row.get("original_asset_sha256"))
            if decision is None:
                pending.append(
                    {
                        "state": row["state"],
                        "id": row["id"],
                        "reason": "missing_original"
                        if "original_path" not in row
                        else "card_boundary_required",
                    }
                )
                continue
            results.append(derive_one(row, decision, rectifier, stage))
            if len(results) % 50 == 0:
                print(f"Normalized and verified {len(results)} references", flush=True)
        if (
            hashlib.sha256(inventory.read_bytes()).hexdigest() != inventory_hash
            or hashlib.sha256(registry.read_bytes()).hexdigest() != registry_hash
        ):
            raise ValueError("Normalization inputs changed during the run")
        manifest = {
            "schema_version": 1,
            "normalization_policy": "id1_50_pixels_per_mm_v1",
            "inventory_sha256": inventory_hash,
            "boundary_registry_sha256": registry_hash,
            "opencv_version": cv2.__version__,
            "input_references": len(rows),
            "normalized_references": len(results),
            "pending_references": len(pending),
            "jurisdictions_with_normalized_references": len({r["state"] for r in results}),
            "counts": dict(sorted(Counter(r["state"] for r in results).items())),
            "results": results,
            "pending": pending,
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
        # Publish a complete run only. An interrupted process cannot leave a partial
        # output that a subsequent publication step could mistake for a finished run.
        os.rename(stage, output)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument(
        "--decisions", type=Path, default=Path("docs/normalization/card-boundaries.json")
    )
    parser.add_argument("--rectifier", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.inventory, args.decisions, args.rectifier, args.output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "input_references",
                    "normalized_references",
                    "pending_references",
                    "jurisdictions_with_normalized_references",
                    "counts",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
