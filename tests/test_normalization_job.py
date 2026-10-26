"""Source-integrity and batch admission tests for recurring normalization."""

import hashlib
import importlib.util
import json

import cv2
import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "normalization_job", "scripts/normalize_references.py"
)
assert spec and spec.loader
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)


def write_registry(path, decisions):
    path.write_text(json.dumps({"schema_version": 1, "decisions": decisions}))


def decision():
    return {
        "original_asset_sha256": "a" * 64,
        "corners": [[0.0, 0.0], [100.0, 0.0], [100.0, 60.0], [0.0, 60.0]],
        "basis": "visual_card_corners",
    }


def test_duplicate_decision_and_symlink_registry_refused(tmp_path):
    path = tmp_path / "registry.json"
    write_registry(path, [decision(), decision()])
    with pytest.raises(ValueError, match="Duplicate"):
        job.decisions_from(path)
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="Invalid or oversized"):
        job.decisions_from(alias)


def test_changed_source_bytes_fail_before_decode(tmp_path, monkeypatch):
    path = tmp_path / "source.png"
    path.write_bytes(b"tampered bytes")
    monkeypatch.setattr(job.cv2, "imdecode", lambda *_: pytest.fail("decoded corrupt source"))
    with pytest.raises(ValueError, match="integrity mismatch"):
        job.decode_original({"original_path": str(path), "original_asset_sha256": "a" * 64})


def test_symlink_source_refused(tmp_path):
    path = tmp_path / "source.png"
    path.write_bytes(b"data")
    alias = tmp_path / "alias.png"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="must not be a symlink"):
        job.decode_original({"original_path": str(alias), "original_asset_sha256": "a" * 64})


def test_original_decode_uses_native_dimensions_and_preserves_bytes(tmp_path):
    pixels = np.arange(100 * 60 * 3, dtype=np.uint8).reshape(60, 100, 3)
    ok, encoded = cv2.imencode(".png", pixels)
    assert ok
    original = encoded.tobytes()
    path = tmp_path / "source.png"
    path.write_bytes(original)
    decoded, retained = job.decode_original(
        {"original_path": str(path), "original_asset_sha256": hashlib.sha256(original).hexdigest()}
    )
    assert retained == original == path.read_bytes()
    np.testing.assert_array_equal(decoded, pixels)


def test_existing_completed_run_is_never_replaced(tmp_path):
    output = tmp_path / "completed"
    output.mkdir()
    receipt = output / "manifest.json"
    receipt.write_text("original receipt")
    with pytest.raises(ValueError, match="already exists"):
        job.run(
            tmp_path / "missing.json", tmp_path / "missing.json", tmp_path / "missing.py", output
        )
    assert receipt.read_text() == "original receipt"


def test_pending_boundaries_are_explicit_and_publish_no_normalized_pixels(tmp_path, monkeypatch):
    inventory, registry = tmp_path / "inventory.json", tmp_path / "registry.json"
    inventory.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "state": "WA",
                        "id": "source-reference",
                        "original_path": "not-opened.png",
                        "original_asset_sha256": "a" * 64,
                    }
                ]
            }
        )
    )
    write_registry(registry, [])
    monkeypatch.setattr(job, "load_rectifier", lambda _: object())
    monkeypatch.setattr(job, "derive_one", lambda *_: pytest.fail("normalized an undecided image"))
    output = tmp_path / "new-run"
    result = job.run(inventory, registry, tmp_path / "rectifier.py", output)
    assert result["normalized_references"] == 0
    assert result["pending"] == [
        {"state": "WA", "id": "source-reference", "reason": "card_boundary_required"}
    ]
    assert json.loads((output / "manifest.json").read_text()) == result
    assert list(output.glob("*.png")) == []


def test_publisher_gate_keeps_canonical_pixels_separate_from_display_footer(tmp_path):
    from types import SimpleNamespace

    from test_normalization import FIXTURES, FrozenRectifier

    from state_id_harvester.normalization import BoundaryDecision, NormalizationGate

    publication_spec = importlib.util.spec_from_file_location(
        "gated_publication", "scripts/vault_sync.py"
    )
    publication = importlib.util.module_from_spec(publication_spec)
    publication_spec.loader.exec_module(publication)
    fixture = FIXTURES["cases"][0]
    source, destination = tmp_path / "source", tmp_path / "prepared"
    source.mkdir()
    destination.mkdir()
    pixels = np.full((fixture["height"], fixture["width"], 3), 127, np.uint8)
    ok, encoded = cv2.imencode(".png", pixels)
    assert ok
    original = encoded.tobytes()
    checksum = hashlib.sha256(original).hexdigest()
    path = source / "card.png"
    path.write_bytes(original)
    boundary = BoundaryDecision(
        original_asset_sha256=checksum, corners=fixture["corners"], basis="visual_native_extent"
    )
    gate = NormalizationGate({checksum: boundary}, FrozenRectifier(fixture))
    doc = SimpleNamespace(
        download=SimpleNamespace(
            source=SimpleNamespace(discovery_jurisdiction="IL", credential_format="ID1"),
            sha256="b" * 64,
        ),
        relevance="candidate",
    )
    asset = SimpleNamespace(path="card.png", sha256=checksum, page_number=1, kind="card_candidate")
    row = publication.prepare_specimen(source, destination, doc, asset, normalization_gate=gate)
    canonical = destination / row["normalization"]["path"]
    analysis = cv2.imread(str(canonical))
    display = cv2.imread(str(destination / f"{row['asset_sha256']}.png"))
    assert analysis.shape == (2699, 4280, 3)
    assert display.shape[1] == 2400
    assert row["transform"]["footer_height_px"] == 110
    assert row["normalization"]["physical_calibration"] is False
    assert row["original_asset_sha256"] == checksum
    assert path.read_bytes() == original
    assert gate.completed == 1 and gate.pending == []
    before = canonical.stat().st_mtime_ns
    repeated = publication.prepare_specimen(
        source, destination, doc, asset, normalization_gate=gate
    )
    assert repeated == row
    assert canonical.stat().st_mtime_ns == before
    assert path.read_bytes() == original
    missing = NormalizationGate({}, object())
    assert (
        publication.prepare_specimen(source, destination, doc, asset, normalization_gate=missing)
        is None
    )
    assert missing.pending == [
        {"original_asset_sha256": checksum, "reason": "card_boundary_required"}
    ]


def test_mismatched_decision_never_writes_a_canonical_image(tmp_path):
    from state_id_harvester.normalization import BoundaryDecision, NormalizationGate

    boundary = BoundaryDecision.model_validate(decision())
    gate = NormalizationGate({"b" * 64: boundary}, object())
    with pytest.raises(ValueError, match="does not match"):
        gate.prepare(np.zeros((60, 100, 3), np.uint8), "b" * 64, tmp_path)
    assert list(tmp_path.iterdir()) == []
