"""Adversarial admission tests: invalid extraction JSON must fail, never be coerced."""

import copy
import json

import pytest
from pydantic import ValidationError

from state_id_harvester.knowledge import DocumentKnowledge, EffectiveDate, load_knowledge
from state_id_harvester.knowledge_evidence import NativePdfPacket, load_grounded_pdf_knowledge

SHA = "a" * 64
QUOTE = "The portrait changes appearance when tilted."


@pytest.fixture
def document() -> dict:
    return {
        "schema_version": 1,
        "source": {
            "source_sha256": SHA,
            "media_type": "application/pdf",
            "availability": "retained",
            "processing": "native_text",
            "page_count": 2,
            "roles": ["issuer_design_reference"],
        },
        "evidence": [
            {
                "kind": "pdf_text",
                "evidence_id": "e1",
                "source_sha256": SHA,
                "page_number": 1,
                "block_index": 0,
                "quote": QUOTE,
            }
        ],
        "sections": [
            {
                "section_id": "s1",
                "title": "Design features",
                "domains": ["credential_design_security"],
                "evidence_ids": ["e1"],
                "page_start": 1,
                "page_end": 1,
            }
        ],
        "subjects": [
            {
                "subject_id": "c1",
                "credential_family": "driver_license",
                "side": "front",
                "evidence_ids": ["e1"],
            }
        ],
        "statements": [
            {
                "statement_id": "k1",
                "section_id": "s1",
                "subject_id": "c1",
                "kind": "assertion",
                "evidence_ids": ["e1"],
                "content": {
                    "domain": "credential_design_security",
                    "name": "Variable portrait",
                    "presence": "present",
                    "inspection_level": 1,
                    "modalities": ["tilt"],
                },
            }
        ],
    }


@pytest.fixture
def packet() -> dict:
    return {
        "schema_version": 1,
        "source_sha256": SHA,
        "extraction": "native_pdf_text_no_ocr",
        "coordinate_system": "PDF page points; top-left origin",
        "pages": [
            {
                "page_number": 1,
                "width_pt": 612.0,
                "height_pt": 792.0,
                "blocks": [
                    {"block_id": 7, "bbox": [72.0, 72.0, 500.0, 100.0], "text": QUOTE + "\n"},
                ],
            },
            {"page_number": 2, "width_pt": 612.0, "height_pt": 792.0, "blocks": []},
        ],
    }


def wire(value: dict) -> bytes:
    return json.dumps(value).encode()


def test_valid_record_roundtrips_and_grounding_preserves_unreviewed_status(document, packet):
    record = load_grounded_pdf_knowledge(wire(document), wire(packet))
    assert record.statements[0].interpretation_status == "unreviewed"
    assert record.evidence[0].quote == QUOTE
    assert load_knowledge(record.model_dump_json().encode()) == record
    assert isinstance(record.sections, tuple)
    with pytest.raises(ValidationError, match="frozen"):
        record.source.page_count = 3


@pytest.mark.parametrize("value", ["2", True, 2.0, 0, -1, None])
def test_pdf_page_count_is_a_real_positive_integer(document, value):
    document["source"]["page_count"] = value
    with pytest.raises(ValidationError):
        load_knowledge(wire(document))


@pytest.mark.parametrize("value", [True, 1.0, "1", 0, 2, None])
def test_schema_version_cannot_be_coerced(document, value):
    document["schema_version"] = value
    with pytest.raises(ValidationError):
        load_knowledge(wire(document))


@pytest.mark.parametrize("value", [True, "1", 1.5, 0, 4])
def test_inspection_levels_are_strict_and_bounded(document, value):
    document["statements"][0]["content"]["inspection_level"] = value
    with pytest.raises(ValidationError):
        load_knowledge(wire(document))


@pytest.mark.parametrize(
    "path,value",
    [
        (("source", "source_sha256"), "abc"),
        (("source", "roles"), ["security_magic"]),
        (("evidence", 0, "quote"), 12),
        (("evidence", 0, "quote"), " \n"),
        (("evidence", 0, "page_number"), True),
        (("evidence", 0, "block_index"), "0"),
        (("evidence", 0, "block_index"), -1),
        (("statements", 0, "content", "modalities"), ["magic_camera"]),
        (("statements", 0, "content", "presence"), True),
        (("statements", 0, "interpretation_status"), "accepted"),
        (("subjects", 0, "issuer"), 42),
        (
            ("statements", 0, "authority_mappings"),
            [
                {
                    "authority": "AAMVA_CDS",
                    "edition": 2026,
                    "clause": "B",
                    "concept": "security",
                }
            ],
        ),
    ],
)
def test_nested_data_types_and_vocabulary_are_enforced(document, path, value):
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        load_knowledge(wire(document))


@pytest.mark.parametrize(
    "part", ["root", "source", "evidence", "section", "subject", "statement", "content"]
)
def test_unknown_fields_cannot_hide_executable_policy_or_geometry(document, part):
    targets = {
        "root": document,
        "source": document["source"],
        "evidence": document["evidence"][0],
        "section": document["sections"][0],
        "subject": document["subjects"][0],
        "statement": document["statements"][0],
        "content": document["statements"][0]["content"],
    }
    targets[part]["executable_rule"] = "reject()"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        load_knowledge(wire(document))


@pytest.mark.parametrize(
    "path,value",
    [
        (("evidence", 0, "source_sha256"), "b" * 64),
        (("statements", 0, "evidence_ids"), ["invented"]),
        (("statements", 0, "evidence_ids"), ["e1", "e1"]),
        (("sections", 0, "domains"), ["credential_design_security"] * 2),
        (("source", "roles"), ["issuer_design_reference"] * 2),
        (("evidence", 0, "page_number"), 3),
        (("evidence", 0, "page_number"), 2),
        (("sections", 0, "page_start"), 2),
        (("sections", 0, "page_end"), None),
        (("statements", 0, "section_id"), "invented"),
        (("statements", 0, "subject_id"), "invented"),
        (("statements", 0, "subject_id"), None),
        (("sections", 0, "domains"), ["acceptance_policy"]),
        (("source", "availability"), "missing_original"),
        (("source", "processing"), "image_only"),
        (
            ("statements", 0, "effective_date"),
            {
                "precision": "month",
                "value": "2026-10",
                "evidence_ids": ["invented"],
            },
        ),
    ],
)
def test_inconsistent_evidence_graphs_fail_admission(document, path, value):
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        load_knowledge(wire(document))


@pytest.mark.parametrize("collection", ["evidence", "sections", "subjects", "statements"])
def test_duplicate_entity_identifiers_are_rejected(document, collection):
    document[collection].append(copy.deepcopy(document[collection][0]))
    with pytest.raises(ValidationError, match="Duplicate"):
        load_knowledge(wire(document))


def test_same_page_does_not_authorize_cross_section_or_subject_leakage(document):
    document["evidence"].append({**document["evidence"][0], "evidence_id": "e2"})
    document["statements"][0]["evidence_ids"] = ["e2"]
    with pytest.raises(ValidationError, match="section's evidence scope"):
        load_knowledge(wire(document))
    document["statements"][0]["evidence_ids"] = ["e1"]
    document["subjects"][0]["evidence_ids"] = ["e2"]
    with pytest.raises(ValidationError, match="subject outside"):
        load_knowledge(wire(document))


def test_text_only_policy_has_no_fabricated_image_or_credential_target(document):
    document["source"]["media_type"] = "text/html"
    document["source"]["page_count"] = None
    document["evidence"] = [
        {
            "kind": "html_text",
            "evidence_id": "e1",
            "source_sha256": SHA,
            "node_path": "/article/section[2]/p[1]",
            "quote": "Temporary cards are accepted here.",
        }
    ]
    document["sections"][0].update(domains=["acceptance_policy"], page_start=None, page_end=None)
    document["subjects"] = []
    statement = document["statements"][0]
    statement["subject_id"] = None
    statement["content"] = {
        "domain": "acceptance_policy",
        "context": "Named source's service",
        "credential_categories": ["temporary card"],
        "outcome": "accepted",
    }
    record = load_knowledge(wire(document))
    assert record.statements[0].subject_id is None
    assert record.source.page_count is None
    document["evidence"][0]["page_number"] = 1
    with pytest.raises(ValidationError):
        load_knowledge(wire(document))


@pytest.mark.parametrize(
    "precision,value",
    [
        ("year", "2026"),
        ("month", "2026-10"),
        ("day", "2024-02-29"),
    ],
)
def test_supported_date_precision_is_retained(precision, value):
    record = EffectiveDate.model_validate_json(
        wire({"precision": precision, "value": value, "evidence_ids": ["e1"]})
    )
    assert record.value == value


@pytest.mark.parametrize(
    "precision,value",
    [
        ("year", "2026-10-01"),
        ("month", "2026-13"),
        ("day", "2025-02-29"),
        ("day", "2026-10"),
        ("year", "0000"),
        ("day", "2026-04-31"),
    ],
)
def test_invalid_or_overprecise_dates_fail(precision, value):
    with pytest.raises(ValidationError):
        EffectiveDate.model_validate_json(
            wire({"precision": precision, "value": value, "evidence_ids": ["e1"]})
        )


@pytest.mark.parametrize("failure", ["hash", "count", "block", "invented_quote", "fuzzy_quote"])
def test_grounding_rejects_exact_quote_and_packet_identity_attacks(document, packet, failure):
    if failure == "hash":
        packet["source_sha256"] = "b" * 64
    elif failure == "count":
        packet["pages"].pop()
    elif failure == "block":
        document["evidence"][0]["block_index"] = 7  # Native block ID is not its array index.
    elif failure == "invented_quote":
        document["evidence"][0]["quote"] = "Unstated security feature"
    else:
        document["evidence"][0]["quote"] = QUOTE.lower()
    with pytest.raises(ValueError):
        load_grounded_pdf_knowledge(wire(document), wire(packet))


@pytest.mark.parametrize(
    "failure",
    ["page_type", "reorder", "duplicate_block", "nan", "infinity", "reverse_bbox", "width_type"],
)
def test_native_packet_types_and_geometry_cannot_be_corrupted(packet, failure):
    page = packet["pages"][0]
    if failure == "page_type":
        page["page_number"] = True
    elif failure == "reorder":
        packet["pages"].reverse()
    elif failure == "duplicate_block":
        page["blocks"].append(copy.deepcopy(page["blocks"][0]))
    elif failure in {"nan", "infinity"}:
        page["blocks"][0]["bbox"][0] = float("nan" if failure == "nan" else "inf")
    elif failure == "reverse_bbox":
        page["blocks"][0]["bbox"] = [500.0, 100.0, 72.0, 72.0]
    else:
        page["width_pt"] = "612.0"
    with pytest.raises(ValidationError):
        NativePdfPacket.model_validate_json(wire(packet))


def test_discriminated_payload_cannot_mix_policy_with_security_fields(document):
    document["statements"][0]["content"]["domain"] = "acceptance_policy"
    with pytest.raises(ValidationError):
        load_knowledge(wire(document))


def test_missing_originals_can_remain_explicit_without_invented_extraction(document):
    source = document["source"]
    source.update(availability="missing_original", processing="pending", page_count=None)
    record = load_knowledge(wire({"source": source}))
    assert record.sections == ()
    assert record.statements == ()


def test_admission_has_an_explicit_size_budget():
    with pytest.raises(ValueError, match="admission budget"):
        load_knowledge(b" " * (8 * 1024 * 1024 + 1))


def test_python_constructor_also_rejects_scalar_coercion(document):
    record = load_knowledge(wire(document))
    data = record.model_dump()
    data["source"]["page_count"] = "2"
    with pytest.raises(ValidationError):
        DocumentKnowledge.model_validate(data)


def test_preconstructed_nested_models_are_revalidated(document):
    record = load_knowledge(wire(document))
    invalid = record.model_copy(
        update={"source": record.source.model_copy(update={"page_count": "2"})}
    )
    with pytest.raises(ValidationError):
        DocumentKnowledge.model_validate(invalid)


@pytest.mark.parametrize(
    "field,value",
    [
        ("retrieved_at", "2026-10-26T12:00:00"),
        ("retrieved_at", 1793052000),
        ("urls", ["file:///private/source.pdf"]),
        ("urls", [12]),
        ("title", False),
    ],
)
def test_source_metadata_types_and_timestamp_timezone_are_enforced(document, field, value):
    document["source"][field] = value
    with pytest.raises(ValidationError):
        load_knowledge(wire(document))


@pytest.mark.parametrize(
    "content",
    [
        {
            "domain": "inspection_procedure",
            "action": "Warm the temporary document as described by the source",
            "expected_observation": "Source-stated color response",
            "modalities": ["thermal", "visible"],
        },
        {
            "domain": "inspection_procedure",
            "action": "Tilt the card",
            "expected_observation": "The portrait changes",
            "modalities": ["tilt"],
        },
        {
            "domain": "issuance_administration",
            "procedure": "Request a replacement",
            "document_stage": "temporary",
            "required_evidence": ["Proof of identity"],
        },
        {
            "domain": "technical_standard",
            "requirement": "Source-stated requirement",
            "authority_reference": {
                "authority": "AAMVA_CDS",
                "edition": "2026",
                "clause": "B",
                "concept": "physical_security",
            },
        },
    ],
)
def test_each_domain_has_its_own_typed_payload(document, content):
    document["sections"][0]["domains"] = [content["domain"]]
    document["statements"][0]["content"] = content
    document["statements"][0]["effective_date"] = {
        "precision": "month",
        "value": "2026-10",
        "evidence_ids": ["e1"],
    }
    record = load_knowledge(wire(document))
    assert record.statements[0].content.domain == content["domain"]
    assert record.statements[0].effective_date.value == "2026-10"


@pytest.mark.parametrize(
    "raw",
    [
        b'{"source":{},"source":{}}',
        b'{"schema_version":1,"source":{"page_count":1,"page_count":2}}',
    ],
)
def test_duplicate_json_fields_are_rejected_before_last_value_wins(raw):
    with pytest.raises(ValueError, match="Duplicate JSON"):
        load_knowledge(raw)


def test_native_packet_cannot_hide_duplicate_fields(document, packet):
    raw = wire(packet).replace(b'"page_number": 1', b'"page_number": 999, "page_number": 1')
    with pytest.raises(ValueError, match="Duplicate JSON"):
        load_grounded_pdf_knowledge(wire(document), raw)


def test_admission_rejects_python_objects_instead_of_json_bytes(document):
    with pytest.raises(TypeError, match="JSON bytes"):
        load_knowledge(document)
