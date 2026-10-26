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
