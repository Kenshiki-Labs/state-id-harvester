"""Backend-neutral, bounded review proposals grounded in existing PDF source lines.

Validation establishes quote/identity/layout binding. It does not establish that
an interpretation is correct or turn prose into executable credential policy.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .document_semantics import BBox, PageSemantics, SourceLine
from .models import Record


class QuotedEvidence(Record):
    span_id: str = Field(min_length=1, max_length=128)
    verbatim_quote: str = Field(min_length=1, max_length=2000)


class SemanticClaim(Record):
    claim_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    target_image_ids: list[str] = Field(min_length=1, max_length=16)
    relation: Literal[
        "source_describes", "source_limits_applicability", "source_comparison", "unresolved"
    ]
    evidence: list[QuotedEvidence] = Field(min_length=1, max_length=32)
    rationale: str = Field(min_length=1, max_length=1500)
    unresolved_questions: list[str] = Field(min_length=1, max_length=16)
    # A narrative comparison never authorizes moving feature zones between designs.
    authorizes_geometry_transfer: Literal[False] = False
    creates_executable_rule: Literal[False] = False


class SemanticReviewProposal(Record):
    schema_version: Literal[1] = 1
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_number: int = Field(ge=1)
    review_origin: Literal["assistant_visual_source_review", "model_backend", "human_source_review"]
    reviewer_or_backend: str = Field(min_length=1, max_length=160)
    claims: list[SemanticClaim] = Field(max_length=64)


class BoundEvidence(Record):
    span_id: str
    verbatim_quote: str
    source_bbox: BBox
    method: Literal["pdf_text", "local_ocr"]
    native_run_ids: list[str]


class GroundedClaim(Record):
    claim: SemanticClaim
    evidence: list[BoundEvidence]
    grounding_status: Literal["source_identity_quotes_and_layout_validated"] = (
        "source_identity_quotes_and_layout_validated"
    )
    semantic_truth_status: Literal["unverified_interpretation"] = "unverified_interpretation"
    geometry_transfer: Literal["not_authorized"] = "not_authorized"
    runtime_use: Literal["none"] = "none"


class SemanticReviewRequest(Record):
    schema_version: Literal[1] = 1
    page: PageSemantics
    task: str = (
        "Relate pictured examples to source statements using the supplied native-object and layout "
        "evidence. Cite existing source span IDs with exact verbatim quotes. Preserve version/date "
        "ambiguity and distinguish narrative feature comparisons from printed layout proof. Return "
        "SemanticReviewProposal only; never infer hidden graphics, field zones or executable rules."
    )
    limits: dict[str, int] = Field(
        default_factory=lambda: {
            "max_claims": 64,
            "max_images_per_claim": 16,
            "max_quotes_per_claim": 32,
        }
    )


def exact_quote(quote: str, line: SourceLine) -> bool:
    # Deliberately no fuzzy quote matching; missing or OCR-corrected words must be reported.
    return quote in line.verbatim_text


def validate_scope(page: PageSemantics, claim: SemanticClaim, line: SourceLine) -> None:
    images = {image.image_id: image for image in page.image_contexts}
    if line.disposition in {"duplicate", "image_transcription", "unresolved_ocr", "page_furniture"}:
        raise ValueError(
            "A source narrative claim cannot be grounded in duplicate/uncertain/image OCR"
        )
    evidence_sections = {
        section.section_id for section in page.sections if line.span_id in section.heading_span_ids
    }
    evidence_sections.update(
        observation.section_id
        for observation in page.observations
        if line.span_id in observation.span_ids
    )
    for target in claim.target_image_ids:
        if target not in images:
            raise ValueError("Semantic proposal refers to an unknown source image placement")
        section_id = images[target].section_id
        if section_id is None or section_id not in evidence_sections:
            raise ValueError("Semantic proposal crosses an unresolved layout/version section")


def ground_claim(page: PageSemantics, claim: SemanticClaim) -> GroundedClaim:
    lines = {line.span_id: line for line in page.source_lines}
    bound = []
    for quote in claim.evidence:
        line = lines.get(quote.span_id)
        if line is None or not exact_quote(quote.verbatim_quote, line):
            raise ValueError("Semantic proposal invents a source span or non-verbatim quote")
        validate_scope(page, claim, line)
        bound.append(
            BoundEvidence(
                span_id=line.span_id,
                verbatim_quote=quote.verbatim_quote,
                source_bbox=line.bbox,
                method=line.method,
                native_run_ids=[run.run_id for run in line.native_runs],
            )
        )
    return GroundedClaim(claim=claim, evidence=bound)


def validate_review(page: PageSemantics, proposal: SemanticReviewProposal) -> list[GroundedClaim]:
    if proposal.source_sha256 != page.source_sha256 or proposal.page_number != page.page_number:
        raise ValueError("Semantic review source hash or page does not match")
    identifiers = [claim.claim_id for claim in proposal.claims]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate semantic claim identifiers")
    return [ground_claim(page, claim) for claim in proposal.claims]


def review_request(page: PageSemantics) -> SemanticReviewRequest:
    if len(page.source_lines) > 5000 or len(page.image_contexts) > 128:
        raise ValueError("Page exceeds bounded semantic review input budget")
    if len(page.model_dump_json().encode()) > 2_000_000:
        raise ValueError("Page exceeds bounded semantic review byte budget")
    return SemanticReviewRequest(page=page)
