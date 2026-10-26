"""Typed native PDF packets and exact quote checks; no OCR or inferred geometry."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .knowledge import (
    Digest,
    DocumentKnowledge,
    Index,
    KnowledgeRecord,
    PdfEvidence,
    PositiveInt,
    validate_json_input,
)

Coordinate = Annotated[float, Field(allow_inf_nan=False)]


class NativeBlock(KnowledgeRecord):
    block_id: Index
    bbox: tuple[Coordinate, Coordinate, Coordinate, Coordinate]
    text: Annotated[str, Field(min_length=1, max_length=1000000)]

    @model_validator(mode="after")
    def validate_bbox(self) -> Self:
        x0, y0, x1, y1 = self.bbox
        if x0 > x1 or y0 > y1:
            raise ValueError("Reversed native block bounds")
        return self


class NativePage(KnowledgeRecord):
    page_number: PositiveInt
    width_pt: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    height_pt: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    blocks: Annotated[tuple[NativeBlock, ...], Field(max_length=10000)]

    @model_validator(mode="after")
    def unique_blocks(self) -> Self:
        ids = [block.block_id for block in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate native block identifiers")
        return self


class NativePdfPacket(KnowledgeRecord):
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    source_sha256: Digest
    extraction: Literal["native_pdf_text_no_ocr"]
    coordinate_system: Literal["PDF page points; top-left origin"]
    pages: Annotated[tuple[NativePage, ...], Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def contiguous_pages(self) -> Self:
        if [page.page_number for page in self.pages] != list(range(1, len(self.pages) + 1)):
            raise ValueError("Native packet pages must be ordered, unique and contiguous")
        return self


def validate_pdf_quotes(knowledge: DocumentKnowledge, packet: NativePdfPacket) -> None:
    """Validate packet anchors; source-byte verification remains the ingest responsibility."""
    if knowledge.source.media_type != "application/pdf":
        raise ValueError("PDF quote validation requires a PDF knowledge record")
    if packet.source_sha256 != knowledge.source.source_sha256:
        raise ValueError("Native packet belongs to another source")
    if knowledge.source.page_count != len(packet.pages):
        raise ValueError("Native packet page count differs from source metadata")
    for evidence in knowledge.evidence:
        if not isinstance(evidence, PdfEvidence):
            raise ValueError("PDF quote validation cannot use HTML evidence")
        blocks = packet.pages[evidence.page_number - 1].blocks
        if evidence.block_index >= len(blocks):
            raise ValueError("Evidence refers to an unknown native block index")
        if evidence.quote not in blocks[evidence.block_index].text:
            raise ValueError("Evidence quote is not verbatim native source text")


def load_grounded_pdf_knowledge(raw: bytes, native_packet: bytes) -> DocumentKnowledge:
    """Admit extraction JSON only after strict model, reference and exact quote validation."""
    from .knowledge import load_knowledge

    validate_json_input(native_packet, 32 * 1024 * 1024)
    knowledge = load_knowledge(raw)
    validate_pdf_quotes(knowledge, NativePdfPacket.model_validate_json(native_packet))
    return knowledge
