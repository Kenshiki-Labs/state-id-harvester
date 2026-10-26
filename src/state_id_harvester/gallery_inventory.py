"""Union verified gallery evidence across runs; keep each run's events separate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .gallery_verify import load_gallery_manifest, verify_gallery
from .storage import now

SECTIONS = ("assets", "pages", "aliases")
TIMESTAMPS = {"retrieved_at", "first_seen_at", "last_seen_at"}


def identity(section: str, item: dict[str, Any]) -> str:
    if section == "assets":
        return str(item["sha256"])
    stable = {key: value for key, value in item.items() if key not in TIMESTAMPS}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


class GalleryInventory:
    def __init__(self, root: Path) -> None:
        self.records: dict[str, list[dict[str, Any]]] = {section: [] for section in SECTIONS}
        self.index: dict[str, dict[str, dict[str, Any]]] = {section: {} for section in SECTIONS}
        self.observed: dict[str, set[str]] = {section: set() for section in SECTIONS}
        self.previous_run_id: str | None = None
        if not (root / "manifest.json").exists():
            return
        prior = load_gallery_manifest(root)
        errors = verify_gallery(root, prior)
        if errors:
            raise ValueError(
                "Prior gallery inventory failed verification: " + ", ".join(errors[:10])
            )
        self.previous_run_id = prior.get("run_id")
        for section in SECTIONS:
            for item in prior[section]:
                self.seed(section, item, prior.get("started_at"))

    def seed(self, section: str, item: dict[str, Any], fallback: Any) -> None:
        key = identity(section, item)
        if key in self.index[section]:
            return
        retained = dict(item)
        first = item.get("first_seen_at") or item.get("retrieved_at") or fallback
        if not isinstance(first, str):
            raise ValueError("Prior gallery object lacks an observation timestamp")
        retained["first_seen_at"] = first
        retained["last_seen_at"] = item.get("last_seen_at") or item.get("retrieved_at") or first
        self.records[section].append(retained)
        self.index[section][key] = retained

    def observe(self, section: str, item: dict[str, Any]) -> None:
        key = identity(section, item)
        stamp = now()
        self.observed[section].add(key)
        if key in self.index[section]:
            self.index[section][key]["last_seen_at"] = stamp
            return
        retained = {**item, "first_seen_at": stamp, "last_seen_at": stamp}
        self.records[section].append(retained)
        self.index[section][key] = retained

    def run_counts(self) -> dict[str, int]:
        return {section: len(self.observed[section]) for section in SECTIONS}
