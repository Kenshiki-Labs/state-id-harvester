"""Explicit public projection: interpretations and citations, never native evidence text."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, HttpUrl, field_validator, model_validator

from .knowledge import (
    Digest,
    DocumentKnowledge,
    Domain,
    Identifier,
    KnowledgeRecord,
    PdfEvidence,
    PositiveInt,
    Role,
    StatementContent,
    Text,
)


class PublicEvidence(KnowledgeRecord):
    page_number: PositiveInt
    url: HttpUrl | None

    @field_validator("url")
    @classmethod
    def public_https(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and (value.scheme != "https" or value.username or value.password):
            raise ValueError("Public citations require credential-free HTTPS")
        return value

    @model_validator(mode="after")
    def matching_page(self) -> Self:
        if self.url is not None and self.url.fragment != f"page={self.page_number}":
            raise ValueError("Citation page fragment mismatch")
        return self


class PublicStatement(KnowledgeRecord):
    statement_id: Identifier
    domain: Domain
    kind: Literal["assertion", "instruction", "requirement", "recommendation", "example"]
    subject: Text | None
    content: StatementContent
    conditions: tuple[Text, ...]
    exceptions: tuple[Text, ...]
    effective_wording: Text | None
    evidence: Annotated[tuple[PublicEvidence, ...], Field(min_length=1)]
    interpretation_status: Literal["unreviewed"] = "unreviewed"

    @model_validator(mode="after")
    def domain_matches(self) -> Self:
        if self.domain != self.content.domain:
            raise ValueError("Public statement domain mismatch")
        return self


class PublicDocument(KnowledgeRecord):
    source_sha256: Digest
    title: Text
    publisher: Text | None
    stated_edition: Text | None = None
    publication_date_wording: Text | None = None
    collection: Text
    source_url: HttpUrl | None
    roles: tuple[Role, ...]
    statement_count: Annotated[int, Field(strict=True, ge=0)]
    statements: tuple[PublicStatement, ...]
    interpretation_status: Literal["unreviewed"] = "unreviewed"

    @field_validator("source_url")
    @classmethod
    def public_https(cls, value: HttpUrl | None) -> HttpUrl | None:
        return PublicEvidence.public_https(value)

    @model_validator(mode="after")
    def accurate_count(self) -> Self:
        if self.statement_count != len(self.statements):
            raise ValueError("Public statement count mismatch")
        base = str(self.source_url).split("#")[0] if self.source_url else None
        for statement in self.statements:
            for citation in statement.evidence:
                citation_base = str(citation.url).split("#")[0] if citation.url else None
                if citation_base != base:
                    raise ValueError("Citation must reference its source publication")
        return self


class PublicKnowledge(KnowledgeRecord):
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    documents: tuple[PublicDocument, ...]

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        keys = [doc.source_sha256 for doc in self.documents]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate public sources")
        return self


def project_document(record: DocumentKnowledge, collection: str) -> PublicDocument:
    """Allowlist fields from a grounded record; no source quote can be copied by default."""
    source_url = next(
        (
            url
            for url in record.source.urls
            if url.scheme == "https" and not url.username and not url.password
        ),
        None,
    )
    evidence = {item.evidence_id: item for item in record.evidence}
    subjects = {item.subject_id: item for item in record.subjects}
    statements = []
    for item in record.statements:
        subject = subjects.get(item.subject_id) if item.subject_id else None
        pages = sorted(
            {
                item_evidence.page_number
                for key in item.evidence_ids
                if isinstance((item_evidence := evidence[key]), PdfEvidence)
            }
        )
        citations = tuple(
            PublicEvidence(
                page_number=page,
                url=HttpUrl(str(source_url).split("#")[0] + f"#page={page}")
                if source_url
                else None,
            )
            for page in pages
        )
        subject_label = None
        if subject:
            subject_label = " · ".join(
                dict.fromkeys(
                    value
                    for value in (
                        subject.design_label,
                        subject.variant,
                        subject.credential_family.replace("_", " "),
                    )
                    if value
                )
            )
        statements.append(
            PublicStatement(
                statement_id=item.statement_id,
                domain=item.content.domain,
                kind=item.kind,
                subject=subject_label,
                content=item.content,
                conditions=item.conditions,
                exceptions=item.exceptions,
                effective_wording=item.effective_wording,
                evidence=citations,
            )
        )
    return PublicDocument(
        source_sha256=record.source.source_sha256,
        title=record.source.title or "Untitled source publication",
        publisher=record.source.publisher,
        stated_edition=record.source.stated_edition,
        publication_date_wording=record.source.publication_date_wording,
        collection=collection,
        source_url=source_url,
        roles=record.source.roles,
        statement_count=len(statements),
        statements=tuple(statements),
    )
