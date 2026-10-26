from __future__ import annotations

import copy
import importlib.util
import json
import sys
from types import SimpleNamespace

import pytest

from state_id_harvester.publication_overlay import PublicationOverlay

spec = importlib.util.spec_from_file_location("overlay_exporter", "scripts/build_public_catalog.py")
assert spec is not None
assert spec.loader is not None
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def citation(sha="a" * 64, url="https://agency.gov/guide.pdf"):
    return {
        "title": "Published credential reference",
        "url": url,
        "sha256": sha,
        "retrieved_at": "",
        "publisher_host": "agency.gov",
        "publisher_jurisdiction": "WA",
        "discovery_jurisdiction": "WA",
        "credential_format": "ID1",
        "relevance": "candidate",
        "review_status": "unreviewed",
        "page_count": 3,
    }


def reference(identity="sample", kind="native_image", sha="a" * 64):
    return {
        "id": identity,
        "source_sha256": sha,
        "asset_sha256": "b" * 64,
        "original_asset_sha256": "c" * 64,
        "kind": kind,
        "page_number": 1,
    }


def overlay():
    return {
        "schema_version": 1,
        "collections": [{"code": "WA", "citations": [citation()], "references": [reference()]}],
    }


def baseline():
    manifest = {"generated_at": "2026-10-26T12:00:00Z", "run_id": "test", "documents": []}
    catalog = exporter.public_catalog(manifest, [], [])
    row = next(row for row in catalog["jurisdictions"] if row["code"] == "WA")
    old = citation("d" * 64, "https://agency.gov/older.pdf")
    old["retrieved_at"] = "2026-10-25T12:00:00Z"
    row["sources"] = [old]
    row["counts"].update(
        sources=1,
        relevant_sources=1,
        embedded_images=4,
        rendered_pages=2,
        crop_candidates=5,
        accepted_cohorts=2,
    )
    row["review_status"] = "reviewed"
    return catalog


def state(catalog):
    return next(row for row in catalog["jurisdictions"] if row["code"] == "WA")


def test_merges_sources_counts_and_retains_baseline_without_promoting_cohorts():
    original = baseline()
    before = copy.deepcopy(original)
    add = overlay()
    collection = add["collections"][0]
    collection["references"].extend(
        [
            reference("native-duplicate"),
            reference("direct", "direct_image"),
            reference("page1", "page_plate"),
            reference("page1-duplicate", "page_plate"),
            {**reference("page2", "page_plate"), "page_number": 2},
        ]
    )
    merged = exporter.merge_publication_overlay(original, add)
    assert original == before
    assert merged["federal"] == before["federal"]
    assert len(merged["jurisdictions"]) == 51
    assert state(merged)["counts"] == {
        "sources": 2,
        "relevant_sources": 2,
        "embedded_images": 5,
        "rendered_pages": 4,
        "crop_candidates": 5,
        "accepted_cohorts": 2,
    }
    assert state(merged)["sources"][0] == state(before)["sources"][0]
    assert state(merged)["review_status"] == "reviewed"
    assert merged["stats"]["accepted_cohorts"] == 2
    assert merged["stats"]["jurisdictions_with_sources"] == 1
    assert exporter.merge_publication_overlay(merged, add) == merged


def test_existing_source_does_not_double_count_images_and_keeps_known_retrieval():
    catalog = baseline()
    known = state(catalog)["sources"][0]
    known["relevance"] = "quarantined"
    add = overlay()
    add["collections"][0]["citations"] = [{**known, "retrieved_at": "", "relevance": "candidate"}]
    add["collections"][0]["references"][0]["source_sha256"] = known["sha256"]
    merged = exporter.merge_publication_overlay(catalog, add)
    assert state(merged)["sources"][0]["retrieved_at"] == known["retrieved_at"]
    assert state(merged)["sources"][0]["relevance"] == "candidate"
    assert state(merged)["counts"]["embedded_images"] == 4
    assert state(merged)["counts"]["relevant_sources"] == 1


@pytest.mark.parametrize(
    "level, field, value",
    [
        ("top", "private_key", "secret"),
        ("collection", "accepted_cohorts", 999),
        ("citation", "raw_text", "private source prose"),
        ("citation", "image_base64", "pixel content"),
        ("reference", "path", "/private/source.png"),
        ("reference", "bbox_uv", [0, 0, 1, 1]),
        ("reference", "accepted", True),
        ("citation", "sha256", "not a hash"),
        ("citation", "review_status", "accepted"),
        ("citation", "retrieved_at", "2026-10-26"),
        ("citation", "title", "Contact person@example.com"),
        ("reference", "source_sha256", "d" * 64),
        ("reference", "id", "../secret"),
        ("reference", "page_number", True),
        ("collection", "code", "US_FED"),
        ("collection", "code", "ZZ"),
        ("citation", "discovery_jurisdiction", "OR"),
        ("citation", "publisher_jurisdiction", "ZZ"),
        ("citation", "publisher_host", "other.gov"),
    ],
)
def test_rejects_unsafe_overlay_atomically(level, field, value):
    add = overlay()
    target = add
    if level != "top":
        target = add["collections"][0]
    if level in {"citation", "reference"}:
        target = target["citations" if level == "citation" else "references"][0]
    target[field] = value
    catalog = baseline()
    before = copy.deepcopy(catalog)
    with pytest.raises(ValueError):
        exporter.merge_publication_overlay(catalog, add)
    assert catalog == before


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://agency.gov/reference.pdf",
        "https://name:password@agency.gov/reference.pdf",
        "file:///private/source.pdf",
        "https://127.0.0.1/source.pdf",
        "https://localhost/source.pdf",
        "https://agency.gov/source.pdf?claim_token=private",
        "https://agency.gov/Users/user/source.pdf",
        "https://agency.gov/file.pdf#private",
        "https://agency.gov/\nfile.pdf",
    ],
)
def test_rejects_private_or_active_citation_urls(url):
    add = overlay()
    add["collections"][0]["citations"][0]["url"] = url
    catalog = baseline()
    with pytest.raises(ValueError):
        exporter.merge_publication_overlay(catalog, add)


@pytest.mark.parametrize("kind", ["citation", "reference", "collection"])
def test_rejects_conflicting_duplicate_identities(kind):
    add = overlay()
    collection = add["collections"][0]
    if kind == "collection":
        add["collections"].append(copy.deepcopy(collection))
    else:
        key = "citations" if kind == "citation" else "references"
        duplicate = copy.deepcopy(collection[key][0])
        duplicate["title" if kind == "citation" else "asset_sha256"] = (
            "Conflicting title" if kind == "citation" else "e" * 64
        )
        collection[key].append(duplicate)
    catalog = baseline()
    with pytest.raises(ValueError):
        exporter.merge_publication_overlay(catalog, add)


def test_same_hash_different_publication_url_is_not_discarded():
    add = overlay()
    add["collections"][0]["citations"].append(citation(url="https://agency.gov/mirror.pdf"))
    merged = exporter.merge_publication_overlay(baseline(), add)
    assert state(merged)["counts"]["sources"] == 3
    assert state(merged)["counts"]["embedded_images"] == 5


def test_existing_accepted_source_cannot_be_downgraded_by_metadata_overlay():
    catalog = baseline()
    old = state(catalog)["sources"][0]
    old["review_status"] = "accepted"
    add = overlay()
    add["collections"][0]["citations"] = [{**old, "review_status": "unreviewed"}]
    add["collections"][0]["references"] = []
    assert (
        state(exporter.merge_publication_overlay(catalog, add))["sources"][0]["review_status"]
        == "accepted"
    )


@pytest.mark.parametrize("version", [True, False, "1", 1.0, 2])
def test_schema_is_strict(version):
    with pytest.raises(ValueError):
        PublicationOverlay.model_validate({"schema_version": version, "collections": []})


@pytest.mark.parametrize("with_overlay", [False, True])
def test_cli_default_overlay_is_optional_and_updates_every_export(
    tmp_path, monkeypatch, with_overlay
):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "coverage.json").write_text("[]")
    manifest = {"generated_at": "2026-10-26T12:00:00Z", "run_id": "test", "documents": []}
    monkeypatch.setattr(
        exporter, "read_manifest", lambda _: SimpleNamespace(model_dump=lambda **_: manifest)
    )
    monkeypatch.setattr(
        exporter,
        "export_catalog",
        lambda model, cohorts, target: target.write_text('{"cohorts": []}'),
    )
    if with_overlay:
        path = tmp_path / "docs/source-research/publication-overlay.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(overlay()))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_public_catalog",
            "--source",
            str(source),
            "--public",
            str(tmp_path / "public"),
            "--library",
            str(tmp_path / "library"),
        ],
    )
    exporter.main()
    catalog = json.loads((tmp_path / "public/data/catalog.json").read_text())
    documents = json.loads((tmp_path / "library/manifest.json").read_text())["documents"]
    assert len(documents) == int(with_overlay)
    assert catalog["stats"]["sources"] == int(with_overlay)
    assert catalog["stats"]["accepted_cohorts"] == 0
    assert json.loads((tmp_path / "library/summary.json").read_text()) == catalog["stats"]
    assert json.loads((tmp_path / "library/coverage.json").read_text()) == catalog["jurisdictions"]
    assert json.loads((tmp_path / "public/data/cohorts.json").read_text())["cohorts"] == []


def test_unpaginated_plates_are_counted_by_unique_asset():
    add = overlay()
    add["collections"][0]["references"] = [
        {**reference("one", "page_plate"), "page_number": None},
        {**reference("two", "page_plate"), "page_number": None, "original_asset_sha256": "e" * 64},
    ]
    assert (
        state(exporter.merge_publication_overlay(baseline(), add))["counts"]["rendered_pages"] == 4
    )


@pytest.mark.parametrize(
    "title",
    [
        "Contact person@example.com",
        "x@y..co",
        "x@domain.COM-extra",
        "prefix a+b.c@domain.gov suffix",
    ],
)
def test_contact_labels_remain_rejected_without_backtracking(title):
    add = overlay()
    add["collections"][0]["citations"][0]["title"] = title
    catalog = baseline()
    with pytest.raises(ValueError):
        exporter.merge_publication_overlay(catalog, add)


@pytest.mark.parametrize("title", ["a" * 240, "x@.co", "x@domain.c", "Public credential guide"])
def test_noncontact_labels_keep_existing_behavior(title):
    add = overlay()
    add["collections"][0]["citations"][0]["title"] = title
    merged = exporter.merge_publication_overlay(baseline(), add)
    assert state(merged)["sources"][-1]["title"] == title
