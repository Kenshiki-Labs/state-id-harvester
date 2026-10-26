"""Delivery preparation rejects damaged inputs and cannot publish an index pointer."""

import hashlib
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "id1_publication", "scripts/prepare_id1_publication.py"
)
assert spec and spec.loader
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value))


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "canonical"
    source.mkdir()
    image = np.full((2699, 4280, 3), 125, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    raw = encoded.tobytes()
    digest = hashlib.sha256(raw).hexdigest()
    (source / f"{digest}.png").write_bytes(raw)
    row = dict(
        state="WA",
        id="sp_test",
        source_sha256="a" * 64,
        original_reference_sha256="b" * 64,
        asset_sha256=digest,
        path=f"{digest}.png",
        width_px=4280,
        height_px=2699,
        boundary_basis="visual_native_extent",
        status="normalized_reference",
    )
    write_json(source / "manifest.json", {"normalized_references": 1, "results": [row]})
    old = tmp_path / "old-index.json"
    write_json(
        old,
        {
            "specimens": [
                dict(
                    state="WA",
                    id="sp_test",
                    source_sha256="a" * 64,
                    asset_sha256="b" * 64,
                    review_status="reference_only",
                    key=f"specimens/original/{'b' * 64}.png",
                )
            ]
        },
    )
    return source, old, tmp_path / "delivery"


def mutate_manifest(source: Path, **changes: object) -> None:
    path = source / "manifest.json"
    data = json.loads(path.read_text())
    data["results"][0].update(changes)
    write_json(path, data)


def test_marked_copy_preserves_canonical_and_lineage(inputs: tuple[Path, Path, Path]) -> None:
    source, old, destination = inputs
    before = {path: path.read_bytes() for path in source.iterdir()}
    before[old] = old.read_bytes()
    result = publication.prepare(source, old, destination)
    row = result["specimens"][0]
    assert (row["width_px"], row["height_px"]) == (4280, 2699)
    raw = (destination / "display" / f"{row['asset_sha256']}.png").read_bytes()
    assert publication.raster_header(raw) == ("png", 2400, 1623)
    assert row["original_reference_sha256"] == "b" * 64
    assert row["canonical_asset_sha256"] != row["asset_sha256"]
    assert row["key"].startswith("specimens/id1/")
    for path, raw in before.items():
        assert path.read_bytes() == raw
    receipt = json.loads((destination / "preparation-receipt.json").read_text())
    assert receipt["lineage"][0]["canonical_resampling_calls"] == 0
    assert receipt["lineage"][0]["delivery_transform"]["footer_height_px"] == 110


@pytest.mark.parametrize(
    "changes",
    [
        {"source_sha256": "f" * 64},
        {"original_reference_sha256": "f" * 64},
        {"id": "unknown"},
        {"width_px": 4280.0},
        {"height_px": 2700},
        {"path": "../secret.png"},
        {"status": "pending"},
        {"boundary_basis": ""},
        {"boundary_basis": "guessed"},
    ],
)
def test_reject_invalid_lineage_and_dimensions_before_writes(
    inputs: tuple[Path, Path, Path],
    changes: dict,
) -> None:
    source, old, destination = inputs
    mutate_manifest(source, **changes)
    with pytest.raises(ValueError):
        publication.prepare(source, old, destination)
    assert not destination.exists()


def test_canonical_tamper_is_rejected(inputs: tuple[Path, Path, Path]) -> None:
    source, old, destination = inputs
    next(source.glob("*.png")).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        publication.prepare(source, old, destination)
    assert not destination.exists()


class FakeVault:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.keys: list[str] = []

    def put(self, key: str, data: bytes, **kwargs: object) -> None:
        assert kwargs["specimen"] is True
        assert kwargs["source_sha256"] == "a" * 64
        self.keys.append(key)
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        return self.objects[key]


def test_upload_only_immutable_display_blobs(inputs: tuple[Path, Path, Path]) -> None:
    source, old, destination = inputs
    publication.prepare(source, old, destination)
    vault = FakeVault()
    receipt = publication.upload_blobs(destination, vault)
    assert len(receipt["verified"]) == 1
    assert receipt["pointer_published"] is False
    assert all(key.startswith("specimens/id1/") for key in vault.keys)
    assert not any(key.startswith("indexes/") for key in vault.keys)


def test_display_tamper_prevents_all_uploads(inputs: tuple[Path, Path, Path]) -> None:
    source, old, destination = inputs
    publication.prepare(source, old, destination)
    next((destination / "display").glob("*.png")).write_bytes(b"tampered")
    vault = FakeVault()
    with pytest.raises(ValueError, match="checksum"):
        publication.upload_blobs(destination, vault)
    assert vault.keys == []


def test_upload_receipt_allows_verified_blob_resume(inputs: tuple[Path, Path, Path]) -> None:
    source, old, destination = inputs
    publication.prepare(source, old, destination)
    first = FakeVault()
    publication.upload_blobs(destination, first)
    resumed = FakeVault()
    receipt = publication.upload_blobs(destination, resumed)
    assert resumed.keys == []
    assert len(receipt["verified"]) == 1


def test_prepared_index_tamper_prevents_upload(inputs: tuple[Path, Path, Path]) -> None:
    source, old, destination = inputs
    publication.prepare(source, old, destination)
    path = destination / "index.json"
    index = json.loads(path.read_text())
    index["specimens"][0]["key"] = "indexes/specimens.json"
    write_json(path, index)
    vault = FakeVault()
    with pytest.raises(ValueError, match="index changed"):
        publication.upload_blobs(destination, vault)
    assert vault.keys == []


def test_global_request_spacing_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    sleeps = []

    def sleep(duration: float) -> None:
        sleeps.append(duration)
        clock[0] += duration

    monkeypatch.setattr(publication.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(publication.time, "sleep", sleep)
    vault = publication.PacedVault("https://vault.example", "test-key")
    try:
        vault.pace()
        vault.pace()
        vault.pace()
    finally:
        vault.close()
    assert sleeps[0] == 0
    assert sleeps[1:] == pytest.approx([0.7, 0.7])


def test_canonical_byte_budget_precedes_read_and_decode(
    inputs: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, old, destination = inputs
    monkeypatch.setattr(publication, "MAX_CANONICAL_BYTES", 8)
    with pytest.raises(ValueError, match="byte budget"):
        publication.prepare(source, old, destination)
    assert not destination.exists()


def test_parent_index_requires_valid_immutable_object_binding(
    inputs: tuple[Path, Path, Path],
) -> None:
    source, old, destination = inputs
    data = json.loads(old.read_text())
    data["specimens"][0]["key"] = "indexes/specimens.json"
    write_json(old, data)
    with pytest.raises(ValueError, match="object key"):
        publication.prepare(source, old, destination)
    assert not destination.exists()
