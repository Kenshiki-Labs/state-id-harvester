from __future__ import annotations

import json
from pathlib import Path

import pytest

from state_id_harvester.models import Download, Event, Options, Source
from state_id_harvester.network import Transport
from state_id_harvester.pipeline import harvest


async def test_resume_reuses_hash_checked_extraction_and_repairs_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_extraction import fixture_pdf

    download = fixture_pdf(tmp_path)
    fetches: list[str] = []

    async def discover(*args: object) -> tuple[list[Source], list[Event]]:
        return [download.source], []

    async def fetch(self: Transport, source: Source, root: Path, options: Options) -> Download:
        fetches.append(source.url)
        return download

    monkeypatch.setattr("state_id_harvester.pipeline.discover_all", discover)
    monkeypatch.setattr(Transport, "download", fetch)
    options = Options(dpi=72, max_render_pages=1, detect_boundaries=False)
    first = await harvest(["CA"], tmp_path, options, tmp_path / "reviews.json")
    second = await harvest(["CA"], tmp_path, options, tmp_path / "reviews.json")
    assert len(first.documents) == len(second.documents) == 1
    assert len(fetches) == 1
    events = json.loads((tmp_path / "events.json").read_text())
    assert any(e["stage"] == "extract" and e["status"] == "cached" for e in events)
    asset = first.documents[0].assets[0]
    (tmp_path / asset.path).write_bytes(b"tampered")
    await harvest(["CA"], tmp_path, options, tmp_path / "reviews.json")
    events = json.loads((tmp_path / "events.json").read_text())
    assert any(e["stage"] == "extract" and e["status"] == "ok" for e in events)
    assert len(fetches) == 1
