"""Real-PDF admission, immutable storage, and malicious input boundary tests."""

import copy
import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from state_id_harvester import knowledge_store as store


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / "retained.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), "Inspect the card under ultraviolet light.")
        pdf.save(source)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    with pymupdf.open(source) as pdf:
        page = pdf[0]
        blocks = [
            {"block_id": b[5], "bbox": list(b[:4]), "text": b[4]}
            for b in page.get_text("blocks")
            if b[6] == 0 and b[4].strip()
        ]
        packet = {
            "schema_version": 1,
            "source_sha256": sha,
            "extraction": "native_pdf_text_no_ocr",
            "coordinate_system": "PDF page points; top-left origin",
            "pages": [
                {
                    "page_number": 1,
                    "width_pt": page.rect.width,
                    "height_pt": page.rect.height,
                    "blocks": blocks,
                }
            ],
        }
    record = {
        "schema_version": 1,
        "source": {
            "source_sha256": sha,
            "media_type": "application/pdf",
            "availability": "retained",
            "processing": "native_text",
            "page_count": 1,
            "roles": ["verification_training"],
        },
        "evidence": [
            {
                "kind": "pdf_text",
                "evidence_id": "e1",
                "source_sha256": sha,
                "page_number": 1,
                "block_index": 0,
                "quote": "Inspect the card under ultraviolet light.",
            }
        ],
        "sections": [
            {
                "section_id": "s1",
                "title": "Inspection",
                "domains": ["inspection_procedure"],
                "evidence_ids": ["e1"],
                "page_start": 1,
                "page_end": 1,
            }
        ],
    }
    packet_path, record_path = tmp_path / "native.json", tmp_path / "knowledge.json"
    packet_path.write_text(json.dumps(packet))
    record_path.write_text(json.dumps(record))
    return source, packet_path, record_path, packet, record


def prepare(inputs, destination):
    return store.prepare_artifacts(*inputs[:3], destination).model_dump(mode="json")


def test_prepare_preserves_sources_and_deterministic_content_addressed_keys(inputs, tmp_path):
    before = [path.read_bytes() for path in inputs[:3]]
    destination = tmp_path / "prepared"
    result = prepare(inputs, destination)
    assert result == prepare(inputs, destination)
    assert [path.read_bytes() for path in inputs[:3]] == before
    assert result["pointer_published"] is False
    assert not (destination / result["pointer_key"]).exists()
    assert len(result["artifacts"]) == 4
    for artifact in result["artifacts"]:
        data = (destination / artifact["key"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == artifact["sha256"]
        assert len(data) == artifact["size_bytes"]
        assert artifact["key"].startswith("snapshots/knowledge/v1/")
    projection = result["registry_projection"]
    assert projection["statement_count"] == 0
    assert projection["section_count"] == 1
    assert "quote" not in json.dumps(projection)
    assert "ultraviolet" not in json.dumps(projection)
    assert len(list((destination / "manifests").glob("*.json"))) == 1


@pytest.mark.parametrize("field,value", [("schema_version", "1"), ("extra", True)])
def test_invalid_knowledge_types_rejected_before_output(inputs, tmp_path, field, value):
    record = copy.deepcopy(inputs[4])
    record[field] = value
    inputs[2].write_text(json.dumps(record))
    destination = tmp_path / "prepared"
    with pytest.raises(ValueError):
        prepare(inputs, destination)
    assert not destination.exists()


def test_invented_quote_rejected(inputs, tmp_path):
    record = inputs[4]
    record["evidence"][0]["quote"] = "An invented source assertion"
    inputs[2].write_text(json.dumps(record))
    with pytest.raises(ValueError, match="not verbatim"):
        prepare(inputs, tmp_path / "prepared")


@pytest.mark.parametrize("mutation", ["text", "geometry", "identifier", "dimensions", "omission"])
def test_forged_packet_with_genuine_source_hash_rejected(inputs, tmp_path, mutation):
    packet, record = inputs[3:]
    block = packet["pages"][0]["blocks"][0]
    if mutation == "text":
        block["text"] = record["evidence"][0]["quote"] = "Forged but self-consistent claim"
    elif mutation == "geometry":
        block["bbox"][0] += 1
    elif mutation == "identifier":
        block["block_id"] += 1
    elif mutation == "dimensions":
        packet["pages"][0]["width_pt"] += 1
    else:
        packet["pages"][0]["blocks"] = []
        record["evidence"] = record["sections"] = []
    inputs[1].write_text(json.dumps(packet))
    inputs[2].write_text(json.dumps(record))
    with pytest.raises(ValueError, match="differ"):
        prepare(inputs, tmp_path / "prepared")


def test_changed_raw_source_rejected(inputs, tmp_path):
    inputs[0].write_bytes(inputs[0].read_bytes() + b"\nchanged")
    with pytest.raises(ValueError, match="source hash"):
        prepare(inputs, tmp_path / "prepared")


@pytest.mark.parametrize("which", [0, 1, 2])
def test_input_symlinks_rejected(inputs, tmp_path, which):
    paths = list(inputs)
    alias = tmp_path / "alias"
    alias.symlink_to(inputs[which])
    paths[which] = alias
    with pytest.raises(ValueError, match="symlinks"):
        prepare(paths, tmp_path / "prepared")


def test_output_symlink_rejected(inputs, tmp_path):
    destination = tmp_path / "prepared"
    destination.mkdir()
    (destination / "snapshots").symlink_to(tmp_path / "escape", target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        prepare(inputs, destination)
    assert not (tmp_path / "escape").exists()


def test_paths_outside_managed_roots_and_traversal_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="managed"):
        store.checked_path(Path("/Users/Shared/outside-knowledge-root"))
    with pytest.raises(ValueError, match="traversal"):
        store.checked_path(tmp_path / ".." / "escape")


@pytest.mark.parametrize("budget", ["MAX_SOURCE_BYTES", "MAX_PACKET_BYTES", "MAX_RECORD_BYTES"])
def test_size_budget_checked_before_preparation(inputs, tmp_path, monkeypatch, budget):
    monkeypatch.setattr(store, budget, 1)
    with pytest.raises(ValueError, match="oversized"):
        prepare(inputs, tmp_path / "prepared")
    assert not (tmp_path / "prepared").exists()


def test_immutable_collision_refused_and_never_overwritten(inputs, tmp_path):
    destination = tmp_path / "prepared"
    result = prepare(inputs, destination)
    path = destination / result["artifacts"][0]["key"]
    corrupted = b"x" * path.stat().st_size
    path.write_bytes(corrupted)
    with pytest.raises(ValueError, match="collision"):
        prepare(inputs, destination)
    assert path.read_bytes() == corrupted


def test_processing_cannot_claim_image_only_for_native_text(inputs, tmp_path):
    record = inputs[4]
    record["source"]["processing"] = "image_only"
    record["evidence"] = record["sections"] = []
    inputs[2].write_text(json.dumps(record))
    with pytest.raises(ValueError, match="processing state"):
        prepare(inputs, tmp_path / "prepared")


def test_image_only_pdf_is_retained_without_fabricating_text(tmp_path):
    source = tmp_path / "image-only.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.save(source)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    packet = {
        "schema_version": 1,
        "source_sha256": sha,
        "extraction": "native_pdf_text_no_ocr",
        "coordinate_system": "PDF page points; top-left origin",
        "pages": [{"page_number": 1, "width_pt": 595.0, "height_pt": 842.0, "blocks": []}],
    }
    record = {
        "source": {
            "source_sha256": sha,
            "media_type": "application/pdf",
            "availability": "retained",
            "processing": "image_only",
            "page_count": 1,
            "roles": ["unresolved"],
        }
    }
    packet_path, record_path = tmp_path / "packet.json", tmp_path / "record.json"
    packet_path.write_text(json.dumps(packet))
    record_path.write_text(json.dumps(record))
    result = store.prepare_artifacts(
        source, packet_path, record_path, tmp_path / "prepared"
    ).model_dump(mode="json")
    assert result["registry_projection"]["processing"] == "image_only"
    assert result["registry_projection"]["statement_count"] == 0


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema_version",), True),
        (("pointer_published",), 0),
        (("pointer_published",), True),
        (("pointer_key",), "indexes/specimens.json"),
        (("artifacts", 0, "size_bytes"), True),
        (("artifacts", 0, "size_bytes"), "100"),
        (("artifacts", 0, "size_bytes"), 0),
        (("artifacts", 0, "size_bytes"), store.MAX_SOURCE_BYTES + 1),
        (("artifacts", 0, "key"), "snapshots/knowledge/v1/sources/../../escape.pdf"),
        (("artifacts", 1, "key"), "snapshots/knowledge/v1/documents/" + "a" * 64 + ".json"),
        (("artifacts", 1, "source_sha256"), "a" * 64),
        (("artifacts", 0, "sha256"), "a" * 64),
        (("registry_projection", "section_count"), "1"),
        (("registry_projection", "section_count"), True),
        (("registry_projection", "source_sha256"), "a" * 64),
        (("registry_projection", "record_sha256"), "a" * 64),
        (
            ("registry_projection", "native_packet_key"),
            "snapshots/knowledge/v1/native-packets/" + "a" * 64 + ".json",
        ),
        (("registry_projection", "statement_count"), 1),
    ],
)
def test_manifest_rejects_invalid_types_keys_and_cross_source_bindings(
    inputs, tmp_path, path, value
):
    raw = prepare(inputs, tmp_path / "prepared")
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        store.PreparedManifest.model_validate_json(json.dumps(raw))


def test_manifest_rejects_duplicate_artifacts_and_unknown_fields(inputs, tmp_path):
    raw = prepare(inputs, tmp_path / "prepared")
    raw["artifacts"][1] = raw["artifacts"][0]
    with pytest.raises(ValueError, match="each artifact kind"):
        store.PreparedManifest.model_validate_json(json.dumps(raw))
    raw = prepare(inputs, tmp_path / "prepared")
    raw["registry_projection"]["quote"] = "This does not belong in the registry"
    with pytest.raises(ValueError):
        store.PreparedManifest.model_validate_json(json.dumps(raw))


def test_prepared_manifest_models_are_frozen_and_validate_roundtrip(inputs, tmp_path):
    manifest = store.prepare_artifacts(*inputs[:3], tmp_path / "prepared")
    assert store.PreparedManifest.model_validate_json(manifest.model_dump_json()) == manifest
    with pytest.raises(ValueError):
        manifest.pointer_published = True
    with pytest.raises(ValueError):
        manifest.artifacts[0].size_bytes = 1


def test_knowledge_index_has_one_typed_current_record_per_source(inputs, tmp_path):
    projection = store.prepare_artifacts(*inputs[:3], tmp_path / "prepared").registry_projection
    index = store.KnowledgeIndex(documents=(projection,))
    assert store.KnowledgeIndex.model_validate_json(index.model_dump_json()) == index
    with pytest.raises(ValueError, match="duplicate source"):
        store.KnowledgeIndex(documents=(projection, projection))
    raw = index.model_dump(mode="json")
    raw["documents"][0]["statement_count"] = "0"
    with pytest.raises(ValueError):
        store.KnowledgeIndex.model_validate_json(json.dumps(raw))
