"""Adversarial public knowledge projection and citation admission tests."""

import copy
import json

import pytest
from pydantic import ValidationError

from state_id_harvester.knowledge import load_knowledge
from state_id_harvester.knowledge_public import PublicKnowledge, project_document

SOURCE = "https://issuer.example.gov/guides/design.pdf?version=legacy"
SHA = "a" * 64


def private_record():
    """Own small source fixture: conditional policy with an explicit historical edition."""
    return {
        "source": {
            "source_sha256": SHA,
            "title": "Legacy specimen inspection guide",
            "publisher": "Example issuer",
            "media_type": "application/pdf",
            "availability": "retained",
            "processing": "native_text",
            "page_count": 3,
            "roles": ["verification_training"],
            "urls": [SOURCE + "#old-fragment"],
            "stated_edition": "Revision 2018-04",
            "publication_date_wording": "Printed April 2018",
        },
        "evidence": [
            {
                "kind": "pdf_text",
                "evidence_id": f"e{page}",
                "source_sha256": SHA,
                "page_number": page,
                "block_index": 0,
                "quote": "Private native source text retained for grounding only.",
            }
            for page in (3, 1)
        ],
        "sections": [
            {
                "section_id": "section",
                "title": "Retail policy",
                "domains": ["acceptance_policy"],
                "evidence_ids": ["e3", "e1"],
                "page_start": 1,
                "page_end": 3,
            }
        ],
        "subjects": [
            {
                "subject_id": "subject",
                "credential_family": "driver_license",
                "side": "front",
                "design_label": "Legacy design only",
                "variant": "Adult",
                "evidence_ids": ["e1"],
            }
        ],
        "statements": [
            {
                "statement_id": "claim",
                "section_id": "section",
                "subject_id": "subject",
                "kind": "recommendation",
                "evidence_ids": ["e3", "e1"],
                "content": {
                    "domain": "acceptance_policy",
                    "context": "Retail alcohol sales",
                    "credential_categories": ["Unexpired photographic DL"],
                    "outcome": "conditional",
                    "conditions": ["Presenter has reached legal age."],
                    "exceptions": ["Temporary paper alone does not qualify."],
                },
                "conditions": ["Only in this source's retail context."],
                "exceptions": ["Stricter premises policy may apply."],
                "effective_wording": "For the April 2018 design described here.",
            }
        ],
    }


def public_payload():
    record = load_knowledge(json.dumps(private_record()).encode())
    projected = project_document(record, "Example collection")
    return json.loads(PublicKnowledge(documents=(projected,)).model_dump_json())


def admit(value):
    return PublicKnowledge.model_validate_json(json.dumps(value))


def test_projection_retains_context_conditions_exceptions_era_and_sorted_citations():
    data = public_payload()["documents"][0]
    statement = data["statements"][0]
    assert statement["conditions"] == ["Only in this source's retail context."]
    assert statement["exceptions"] == ["Stricter premises policy may apply."]
    assert statement["content"]["conditions"] == ["Presenter has reached legal age."]
    assert statement["content"]["exceptions"] == ["Temporary paper alone does not qualify."]
    assert statement["effective_wording"] == "For the April 2018 design described here."
    assert statement["kind"] == "recommendation"
    assert "Legacy design only" in statement["subject"]
    assert "Adult" in statement["subject"]
    assert data["collection"] == "Example collection"
    assert data["publisher"] == "Example issuer"
    assert [e["page_number"] for e in statement["evidence"]] == [1, 3]
    assert [e["url"] for e in statement["evidence"]] == [
        SOURCE + "#page=1",
        SOURCE + "#page=3",
    ]
    assert data["stated_edition"] == "Revision 2018-04"
    assert data["publication_date_wording"] == "Printed April 2018"
    serialized = json.dumps(data)
    for private_field in (
        "quote",
        "block_index",
        "evidence_id",
        "section_id",
        "source_original_path",
    ):
        assert f'"{private_field}"' not in serialized
    assert "Private native source text" not in serialized
    assert data["interpretation_status"] == statement["interpretation_status"] == "unreviewed"


@pytest.mark.parametrize("target", ["root", "document", "statement", "evidence", "content"])
@pytest.mark.parametrize("name", ["quote", "raw_path", "native_packet_path"])
def test_unknown_evidence_text_and_filesystem_fields_are_rejected(target, name):
    data = public_payload()
    targets = {
        "root": data,
        "document": data["documents"][0],
        "statement": data["documents"][0]["statements"][0],
        "evidence": data["documents"][0]["statements"][0]["evidence"][0],
        "content": data["documents"][0]["statements"][0]["content"],
    }
    targets[target][name] = "/private/source.pdf" if "path" in name else "native quote"
    with pytest.raises(ValidationError):
        admit(data)


@pytest.mark.parametrize("level", ["document", "statement"])
@pytest.mark.parametrize("status", ["reviewed", "accepted", "verified", True])
def test_public_projection_cannot_promote_review_status(level, status):
    data = public_payload()
    target = data["documents"][0]
    if level == "statement":
        target = target["statements"][0]
    target["interpretation_status"] = status
    with pytest.raises(ValidationError):
        admit(data)


@pytest.mark.parametrize(
    "url",
    [
        "http://issuer.example.gov/guide.pdf",
        "file:///private/guide.pdf",
        "javascript:alert(1)",
        "https://user:secret@issuer.example.gov/guide.pdf",
        "https://user@issuer.example.gov/guide.pdf",
        "not a URL",
    ],
)
@pytest.mark.parametrize("level", ["source", "page"])
def test_invalid_or_credentialed_public_urls_are_rejected(url, level):
    data = public_payload()
    doc = data["documents"][0]
    if level == "source":
        doc["source_url"] = url
    else:
        doc["statements"][0]["evidence"][0]["url"] = url
    with pytest.raises(ValidationError):
        admit(data)


@pytest.mark.parametrize(
    "url",
    [
        SOURCE + "#page=999",
        SOURCE + "#page=0",
        SOURCE + "#section=1",
        SOURCE,
        "https://unrelated.example.gov/other.pdf#page=1",
        "https://issuer.example.gov/guides/other.pdf?version=legacy#page=1",
    ],
)
def test_citations_cannot_change_source_or_lie_about_physical_page(url):
    data = public_payload()
    data["documents"][0]["statements"][0]["evidence"][0]["url"] = url
    with pytest.raises(ValidationError):
        admit(data)


@pytest.mark.parametrize("count", [0, 2, True, "1", 1.0])
def test_counts_cannot_disagree_or_be_coerced(count):
    data = public_payload()
    data["documents"][0]["statement_count"] = count
    with pytest.raises(ValidationError):
        admit(data)


def test_statement_domain_must_match_typed_content():
    data = public_payload()
    data["documents"][0]["statements"][0]["domain"] = "credential_design_security"
    with pytest.raises(ValidationError):
        admit(data)


def test_duplicate_source_digest_is_rejected():
    data = public_payload()
    data["documents"].append(copy.deepcopy(data["documents"][0]))
    with pytest.raises(ValidationError):
        admit(data)


def test_https_source_selection_skips_unsafe_alias_and_removes_old_fragment():
    raw = private_record()
    raw["source"]["urls"] = [
        "http://issuer.example.gov/legacy.pdf",
        "https://user:secret@issuer.example.gov/private.pdf",
        SOURCE + "#old-fragment",
    ]
    doc = project_document(load_knowledge(json.dumps(raw).encode()), "Example")
    assert str(doc.source_url) == SOURCE + "#old-fragment"
    assert str(doc.statements[0].evidence[0].url) == SOURCE + "#page=1"


def test_missing_safe_alias_yields_explicit_null_citation_instead_of_private_link():
    raw = private_record()
    raw["source"]["urls"] = ["http://issuer.example.gov/legacy.pdf"]
    doc = project_document(load_knowledge(json.dumps(raw).encode()), "Example")
    assert doc.source_url is None
    assert all(e.url is None for e in doc.statements[0].evidence)


@pytest.fixture
def public_exporter():
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "export_public_knowledge.py"
    spec = importlib.util.spec_from_file_location("public_knowledge_exporter_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_managed_record_allows_existing_digest_named_record(public_exporter, tmp_path):
    root = tmp_path / "workspace"
    path = root / "output" / "knowledge" / "run" / (SHA + ".json")
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    assert public_exporter.managed_record(path, root) == path.resolve()


@pytest.mark.parametrize("escape", ["absolute", "traversal"])
def test_managed_record_rejects_existing_file_outside_managed_knowledge(
    public_exporter, tmp_path, escape
):
    root = tmp_path / "workspace"
    allowed = root / "output" / "knowledge"
    allowed.mkdir(parents=True)
    outside = root / "output" / "unrelated" / (SHA + ".json")
    outside.parent.mkdir()
    outside.write_text("do not read this unrelated record")
    candidate = outside if escape == "absolute" else allowed / ".." / "unrelated" / outside.name
    with pytest.raises(ValueError):
        public_exporter.managed_record(candidate, root)


def test_managed_record_rejects_symlink_file_escape(public_exporter, tmp_path):
    root = tmp_path / "workspace"
    allowed = root / "output" / "knowledge"
    allowed.mkdir(parents=True)
    outside = tmp_path / "private-record.json"
    outside.write_text("do not read this private record")
    candidate = allowed / (SHA + ".json")
    candidate.symlink_to(outside)
    with pytest.raises(ValueError):
        public_exporter.managed_record(candidate, root)


def test_managed_record_rejects_symlink_parent_escape(public_exporter, tmp_path):
    root = tmp_path / "workspace"
    allowed = root / "output" / "knowledge"
    allowed.mkdir(parents=True)
    outside = tmp_path / "private-run"
    outside.mkdir()
    (outside / (SHA + ".json")).write_text("{}")
    link = allowed / "run"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        public_exporter.managed_record(link / (SHA + ".json"), root)


@pytest.mark.parametrize("filename", ["record.json", "a.json", "g" * 64 + ".json", SHA + ".txt"])
def test_managed_record_rejects_wrong_record_filename(public_exporter, tmp_path, filename):
    root = tmp_path / "workspace"
    path = root / "output" / "knowledge" / filename
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    with pytest.raises(ValueError):
        public_exporter.managed_record(path, root)


def test_managed_record_rejects_missing_record(public_exporter, tmp_path):
    root = tmp_path / "workspace"
    allowed = root / "output" / "knowledge"
    allowed.mkdir(parents=True)
    with pytest.raises((ValueError, FileNotFoundError)):
        public_exporter.managed_record(allowed / (SHA + ".json"), root)


def test_managed_record_rejects_directory_disguised_as_record(public_exporter, tmp_path):
    root = tmp_path / "workspace"
    path = root / "output" / "knowledge" / (SHA + ".json")
    path.mkdir(parents=True)
    with pytest.raises(ValueError):
        public_exporter.managed_record(path, root)


def test_managed_record_rejects_symlink_even_when_target_stays_managed(public_exporter, tmp_path):
    root = tmp_path / "workspace"
    allowed = root / "output" / "knowledge"
    allowed.mkdir(parents=True)
    target = allowed / ("b" * 64 + ".json")
    target.write_text("{}")
    link = allowed / (SHA + ".json")
    link.symlink_to(target)
    with pytest.raises(ValueError):
        public_exporter.managed_record(link, root)


def test_managed_record_rejects_symlinked_knowledge_root(public_exporter, tmp_path):
    root = tmp_path / "workspace"
    (root / "output").mkdir(parents=True)
    relocated = root / "relocated-knowledge"
    relocated.mkdir()
    (relocated / (SHA + ".json")).write_text("{}")
    (root / "output" / "knowledge").symlink_to(relocated, target_is_directory=True)
    with pytest.raises(ValueError):
        public_exporter.managed_record(root / "output" / "knowledge" / (SHA + ".json"), root)


def reference_payload():
    return {
        "id": "specimen_front-01",
        "state": "WA",
        "source_sha256": SHA,
        "asset_sha256": "b" * 64,
        "source_page": 2,
    }


def test_exact_matching_reference_images_survive_projection():
    from state_id_harvester.knowledge_public import PublicReference

    reference = PublicReference.model_validate_json(json.dumps(reference_payload()))
    projected = project_document(
        load_knowledge(json.dumps(private_record()).encode()), "Example", (reference,)
    )
    assert projected.references == (reference,)
    assert projected.references[0].source_page == 2
    assert projected.references[0].source_sha256 == projected.source_sha256
    assert json.loads(projected.model_dump_json())["references"] == [reference_payload()]


def test_reference_images_default_to_empty_without_inventing_association():
    doc = public_payload()["documents"][0]
    assert doc["references"] == []


def test_reference_from_another_source_cannot_attach_to_public_document():
    data = public_payload()
    reference = reference_payload()
    reference["source_sha256"] = "c" * 64
    data["documents"][0]["references"] = [reference]
    with pytest.raises(ValidationError):
        admit(data)


def test_duplicate_state_id_reference_rejected_even_with_different_asset_hash():
    data = public_payload()
    first = reference_payload()
    second = dict(first, asset_sha256="c" * 64, source_page=3)
    data["documents"][0]["references"] = [first, second]
    with pytest.raises(ValidationError):
        admit(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", ""),
        ("id", "../secret"),
        ("id", "/private/path"),
        ("id", "x" * 151),
        ("id", True),
        ("id", 42),
        ("state", "wa"),
        ("state", "WASHINGTON"),
        ("state", "W"),
        ("state", True),
        ("source_sha256", "a" * 63),
        ("source_sha256", "g" * 64),
        ("source_sha256", True),
        ("source_sha256", 42),
        ("asset_sha256", "A" * 64),
        ("asset_sha256", "../asset"),
        ("asset_sha256", None),
        ("asset_sha256", 42),
        ("source_page", 0),
        ("source_page", -1),
        ("source_page", "2"),
        ("source_page", True),
        ("source_page", 2.0),
    ],
)
def test_invalid_reference_identifiers_hashes_and_page_types_rejected(field, value):
    data = public_payload()
    reference = reference_payload()
    reference[field] = value
    data["documents"][0]["references"] = [reference]
    with pytest.raises(ValidationError):
        admit(data)


@pytest.mark.parametrize("state", ["WA", "US_FED"])
def test_valid_reference_state_and_unknown_source_page_are_retained(state):
    data = public_payload()
    reference = dict(reference_payload(), state=state, source_page=None)
    data["documents"][0]["references"] = [reference]
    accepted = admit(data).documents[0].references[0]
    assert accepted.state == state
    assert accepted.source_page is None
