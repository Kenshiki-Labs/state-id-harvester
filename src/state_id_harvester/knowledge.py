"""Strict ontology interchange. Valid structure and grounding do not prove an interpretation."""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

from .models import SHA256_PATTERN, Record

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
Digest = Annotated[str, StringConstraints(pattern=SHA256_PATTERN)]
Text = Annotated[str, StringConstraints(min_length=1, max_length=2000, pattern=r"\S")]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
Index = Annotated[int, Field(strict=True, ge=0)]
EvidenceIds = Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=128)]
Domain = Literal[
    "credential_design_security",
    "inspection_procedure",
    "acceptance_policy",
    "issuance_administration",
    "technical_standard",
    "other",
    "unresolved",
]
Role = Literal[
    "technical_standard",
    "legislation_regulation",
    "issuer_design_reference",
    "verification_training",
    "issuance_guidance",
    "design_announcement",
    "operational_manual",
    "unresolved",
]
Modality = Literal[
    "visible",
    "tilt",
    "transmitted_light",
    "ultraviolet",
    "infrared",
    "magnification",
    "tactile",
    "thermal",
    "barcode",
    "magstripe",
    "rfid",
]


class KnowledgeRecord(Record):
    """No coercion, unknown fields, nonfinite numbers or mutable record collections."""

    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, allow_inf_nan=False, revalidate_instances="always"
    )


class SourcePublication(KnowledgeRecord):
    source_sha256: Digest
    title: Text | None = None
    publisher: Text | None = None
    publisher_jurisdiction: Text | None = None
    urls: Annotated[tuple[HttpUrl, ...], Field(max_length=64)] = ()
    retrieved_at: AwareDatetime | None = None
    stated_edition: Text | None = None
    publication_date_wording: Text | None = None
    media_type: Literal[
        "application/pdf",
        "text/html",
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "unknown",
    ]
    availability: Literal["retained", "missing_original"]
    processing: Literal["pending", "native_text", "image_only", "parse_failed", "not_applicable"]
    page_count: PositiveInt | None = None
    roles: Annotated[tuple[Role, ...], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("Duplicate publication roles")
        if self.availability == "missing_original" and (
            self.processing != "pending" or self.page_count is not None
        ):
            raise ValueError("Missing originals cannot have extracted page metadata")
        if self.media_type != "application/pdf" and self.page_count is not None:
            raise ValueError("Only PDFs have physical PDF page counts")
        if self.media_type == "application/pdf" and self.processing in {
            "native_text",
            "image_only",
        }:
            if self.page_count is None:
                raise ValueError("Parsed PDFs require page counts")
        if self.processing == "native_text" and self.media_type not in {
            "application/pdf",
            "text/html",
        }:
            raise ValueError("Native text requires PDF or HTML content")
        if self.processing == "image_only" and self.media_type != "application/pdf":
            raise ValueError("Image-only is a PDF processing state")
        return self


class PdfEvidence(KnowledgeRecord):
    kind: Literal["pdf_text"]
    evidence_id: Identifier
    source_sha256: Digest
    page_number: PositiveInt
    # Zero-based index in the retained native packet's blocks array, not an image xref.
    block_index: Index
    quote: Text


class HtmlEvidence(KnowledgeRecord):
    kind: Literal["html_text"]
    evidence_id: Identifier
    source_sha256: Digest
    node_path: Annotated[str, StringConstraints(min_length=1, max_length=1024, pattern=r"\S")]
    quote: Text


Evidence = Annotated[PdfEvidence | HtmlEvidence, Field(discriminator="kind")]


class DocumentSection(KnowledgeRecord):
    section_id: Identifier
    title: Text
    domains: Annotated[tuple[Domain, ...], Field(min_length=1, max_length=7)]
    evidence_ids: EvidenceIds
    page_start: PositiveInt | None = None
    page_end: PositiveInt | None = None

    @model_validator(mode="after")
    def validate_section(self) -> Self:
        if len(self.domains) != len(set(self.domains)):
            raise ValueError("Duplicate section domains")
        if (self.page_start is None) != (self.page_end is None):
            raise ValueError("Section page bounds must be supplied together")
        if self.page_start is not None and self.page_end is not None:
            if self.page_start > self.page_end:
                raise ValueError("Reversed section page bounds")
        return self


class CredentialSubject(KnowledgeRecord):
    subject_id: Identifier
    issuer: Text | None = None
    jurisdiction: Text | None = None
    credential_family: Literal[
        "driver_license",
        "identification_card",
        "permit",
        "passport",
        "passport_card",
        "permanent_resident_card",
        "employment_authorization",
        "other",
        "unknown",
    ]
    design_label: Text | None = None
    variant: Text | None = None
    side: Literal["front", "back", "both", "unknown"]
    evidence_ids: EvidenceIds


class AuthorityReference(KnowledgeRecord):
    """An edition/clause reference, not an issuer-adoption or compliance assertion."""

    authority: Text
    edition: Text
    clause: Text
    concept: Text
    mapping_status: Literal["proposed", "reviewed"] = "proposed"


class EffectiveDate(KnowledgeRecord):
    precision: Literal["year", "month", "day"]
    value: Annotated[str, StringConstraints(pattern=r"^\d{4}(?:-\d{2})?(?:-\d{2})?$")]
    evidence_ids: EvidenceIds

    @model_validator(mode="after")
    def validate_date(self) -> Self:
        lengths = {"year": 4, "month": 7, "day": 10}
        if len(self.value) != lengths[self.precision]:
            raise ValueError("Date precision and value disagree")
        suffix = {"year": "-01-01", "month": "-01", "day": ""}[self.precision]
        date.fromisoformat(self.value + suffix)
        return self


class DesignFeature(KnowledgeRecord):
    domain: Literal["credential_design_security"]
    name: Text
    presence: Literal["present", "absent"]
    security_family: (
        Literal[
            "card_body",
            "reproduction_resistance",
            "security_inks",
            "personalization_protection",
        ]
        | None
    ) = None
    inspection_level: Annotated[int, Field(strict=True, ge=1, le=3)] | None = None
    modalities: Annotated[tuple[Modality, ...], Field(max_length=11)] = ()
    source_location: Text | None = None


class InspectionProcedure(KnowledgeRecord):
    domain: Literal["inspection_procedure"]
    action: Text
    expected_observation: Text
    modalities: Annotated[tuple[Modality, ...], Field(min_length=1, max_length=11)]
    equipment: Annotated[tuple[Text, ...], Field(max_length=20)] = ()


class AcceptancePolicy(KnowledgeRecord):
    domain: Literal["acceptance_policy"]
    context: Text
    credential_categories: Annotated[tuple[Text, ...], Field(min_length=1, max_length=32)]
    outcome: Literal["accepted", "not_accepted", "conditional"]
    conditions: Annotated[tuple[Text, ...], Field(max_length=32)] = ()
    exceptions: Annotated[tuple[Text, ...], Field(max_length=32)] = ()


class IssuanceGuidance(KnowledgeRecord):
    domain: Literal["issuance_administration"]
    procedure: Text
    required_evidence: Annotated[tuple[Text, ...], Field(max_length=32)] = ()
    document_stage: Literal["temporary", "permanent", "both", "unspecified"]


class StandardRequirement(KnowledgeRecord):
    domain: Literal["technical_standard"]
    requirement: Text
    authority_reference: AuthorityReference


StatementContent = Annotated[
    DesignFeature | InspectionProcedure | AcceptancePolicy | IssuanceGuidance | StandardRequirement,
    Field(discriminator="domain"),
]


class ExtractedStatement(KnowledgeRecord):
    statement_id: Identifier
    section_id: Identifier
    subject_id: Identifier | None = None
    kind: Literal["assertion", "instruction", "requirement", "recommendation", "example"]
    content: StatementContent
    evidence_ids: EvidenceIds
    conditions: Annotated[tuple[Text, ...], Field(max_length=32)] = ()
    exceptions: Annotated[tuple[Text, ...], Field(max_length=32)] = ()
    effective_wording: Text | None = None
    effective_date: EffectiveDate | None = None
    authority_mappings: Annotated[tuple[AuthorityReference, ...], Field(max_length=16)] = ()
    interpretation_status: Literal["unreviewed"] = "unreviewed"


def unique_ids(values: tuple[str, ...]) -> None:
    if len(values) != len(set(values)):
        raise ValueError("Duplicate record or evidence identifiers")


class DocumentKnowledge(KnowledgeRecord):
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    source: SourcePublication
    evidence: Annotated[tuple[Evidence, ...], Field(max_length=10000)] = ()
    sections: Annotated[tuple[DocumentSection, ...], Field(max_length=2000)] = ()
    subjects: Annotated[tuple[CredentialSubject, ...], Field(max_length=1000)] = ()
    statements: Annotated[tuple[ExtractedStatement, ...], Field(max_length=10000)] = ()

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        evidence = {item.evidence_id: item for item in self.evidence}
        sections = {item.section_id: item for item in self.sections}
        subjects = {item.subject_id: item for item in self.subjects}
        for identifiers in (
            tuple(item.evidence_id for item in self.evidence),
            tuple(item.section_id for item in self.sections),
            tuple(item.subject_id for item in self.subjects),
            tuple(item.statement_id for item in self.statements),
        ):
            unique_ids(identifiers)
        self.validate_evidence()
        for section in self.sections:
            self.validate_section_scope(section, evidence)
        for subject in self.subjects:
            self.validate_references(subject.evidence_ids, evidence)
        for statement in self.statements:
            self.validate_statement(statement, evidence, sections, subjects)
        return self

    def validate_statement(
        self,
        statement: ExtractedStatement,
        evidence: dict[str, Evidence],
        sections: dict[str, DocumentSection],
        subjects: dict[str, CredentialSubject],
    ) -> None:
        containing_section = sections.get(statement.section_id)
        if containing_section is None or statement.content.domain not in containing_section.domains:
            raise ValueError("Statement has no matching classified section domain")
        self.validate_references(statement.evidence_ids, evidence)
        if not set(statement.evidence_ids).issubset(containing_section.evidence_ids):
            raise ValueError("Statement crosses its section's evidence scope")
        self.validate_subject(statement, containing_section, subjects)
        if statement.effective_date is not None:
            unique_ids(statement.effective_date.evidence_ids)
            if not set(statement.effective_date.evidence_ids).issubset(statement.evidence_ids):
                raise ValueError("Effective date lacks statement evidence")

    def validate_evidence(self) -> None:
        for item in self.evidence:
            if (
                self.source.availability != "retained"
                or item.source_sha256 != self.source.source_sha256
            ):
                raise ValueError("Evidence source is missing or has a different hash")
            if isinstance(item, PdfEvidence):
                count = self.source.page_count
                if (
                    self.source.media_type != "application/pdf"
                    or count is None
                    or item.page_number > count
                ):
                    raise ValueError("PDF evidence lies outside its source")
                if self.source.processing != "native_text":
                    raise ValueError("PDF text evidence requires native text extraction")
            elif self.source.media_type != "text/html" or self.source.processing != "native_text":
                raise ValueError("HTML evidence requires native HTML extraction")

    @staticmethod
    def validate_references(ids: tuple[str, ...], evidence: dict[str, Evidence]) -> None:
        unique_ids(ids)
        if not set(ids).issubset(evidence):
            raise ValueError("Unknown evidence reference")

    def validate_section_scope(
        self, section: DocumentSection, evidence: dict[str, Evidence]
    ) -> None:
        self.validate_references(section.evidence_ids, evidence)
        if self.source.media_type != "application/pdf":
            if section.page_start is not None:
                raise ValueError("Non-PDF sections cannot have PDF page bounds")
            return
        start, end, count = section.page_start, section.page_end, self.source.page_count
        if start is None or end is None or count is None or end > count:
            raise ValueError("PDF section bounds lie outside its source")
        for identifier in section.evidence_ids:
            item = evidence[identifier]
            if isinstance(item, PdfEvidence) and not start <= item.page_number <= end:
                raise ValueError("Section evidence lies outside its page bounds")

    @staticmethod
    def validate_subject(
        statement: ExtractedStatement,
        section: DocumentSection,
        subjects: dict[str, CredentialSubject],
    ) -> None:
        if statement.subject_id is None:
            if isinstance(statement.content, (DesignFeature, InspectionProcedure)):
                raise ValueError("Credential features and inspections require a subject")
            return
        subject = subjects.get(statement.subject_id)
        if subject is None or not set(subject.evidence_ids).issubset(section.evidence_ids):
            raise ValueError("Unknown subject or subject outside the section evidence scope")


def unique_json_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object field")
        result[key] = value
    return result


def validate_json_input(raw: bytes, limit: int) -> None:
    if not isinstance(raw, bytes):
        raise TypeError("Admission requires UTF-8 JSON bytes")
    if len(raw) > limit:
        raise ValueError("JSON exceeds its admission budget")
    # Pydantic's JSON parser otherwise keeps the last duplicate key silently.
    json.loads(raw, object_pairs_hook=unique_json_fields)


def load_knowledge(raw: bytes) -> DocumentKnowledge:
    """The admission boundary for native/model extraction JSON, before persistence or indexing."""
    validate_json_input(raw, 8 * 1024 * 1024)
    return DocumentKnowledge.model_validate_json(raw)
