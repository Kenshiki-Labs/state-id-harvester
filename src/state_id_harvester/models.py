"""Versioned, validated on-disk contracts. Paths are relative to the library root."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Source(Record):
    discovery_jurisdiction: str = Field(pattern=r"^[A-Z]{2}$")
    url: str
    discovered_via: str
    link_text: str | None = None


class Download(Record):
    source: Source
    final_url: str
    retrieved_at: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=1)
    path: str
    content_type: str
    publisher_host: str
    publisher_jurisdiction: str | None = None
    etag: str | None = None
    last_modified: str | None = None


class Asset(Record):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    kind: Literal[
        "extracted_image",
        "raw_stream",
        "page_render",
        "thumbnail",
        "text",
        "geometry",
        "card_candidate",
    ]
    page_number: int | None = None
    xref: int | None = None
    width: int | None = None
    height: int | None = None


class TextBlock(Record):
    page_number: int
    bbox: tuple[float, float, float, float]
    text: str
    method: Literal["pdf_text", "local_ocr"] = "pdf_text"
    ocr_confidence: float | None = None


class Placement(Record):
    bbox: tuple[float, float, float, float]
    transform: tuple[float, float, float, float, float, float]


class ImageGeometry(Record):
    xref: int
    smask_xref: int
    width: int
    height: int
    colorspace: str
    pdf_object: str
    raw_stream_path: str
    extracted_path: str | None
    smask_stream_path: str | None
    placements: list[Placement]


class PageGeometry(Record):
    page_number: int
    mediabox: tuple[float, float, float, float]
    cropbox: tuple[float, float, float, float]
    rotation: int
    rotation_matrix: tuple[float, float, float, float, float, float]
    pdf_to_mupdf_matrix: tuple[float, float, float, float, float, float]
    matched_features: list[str]
    images: list[ImageGeometry]
    rendered: bool
    render_tiles: list[dict[str, object]] = Field(default_factory=list)
    render_skip_reason: str | None = None


class Document(Record):
    schema_version: Literal[1] = 1
    download: Download
    extractor_version: str
    extraction_fingerprint: str
    pymupdf_version: str
    title: str
    page_count: int
    matched_features: list[str]
    relevance: Literal["candidate", "quarantined"]
    relevance_reason: str
    assets: list[Asset]
    warnings: list[str]
    # Publisher location is never used as the depicted credential's jurisdiction.
    review_status: Literal["unreviewed"] = "unreviewed"


class Review(Record):
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    asset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    depicted_jurisdiction: str = Field(pattern=r"^[A-Z]{2}$")
    credential_type: Literal["driver_license", "identification_card", "learner_permit"]
    design_generation: str = Field(min_length=1)
    side: Literal["front", "back", "both", "detail"]
    status: Literal["accepted", "rejected"]
    reviewer: str = Field(min_length=1)
    reviewed_at: str
    evidence: str = Field(min_length=1)

    @field_validator("depicted_jurisdiction")
    @classmethod
    def valid_jurisdiction(cls, value: str) -> str:
        from .seeds import STATE_DOMAINS

        if value not in STATE_DOMAINS:
            raise ValueError("Unknown US jurisdiction")
        return value


class Event(Record):
    at: str
    jurisdiction: str
    url: str
    stage: Literal["discovery", "fetch", "extract"]
    status: Literal["ok", "cached", "failed", "skipped"]
    detail: str


class Options(Record):
    dpi: int = Field(default=600, ge=72, le=600)
    max_pdf_bytes: int = Field(default=36_700_160, ge=1)
    min_pdf_bytes: int = Field(default=25_000, ge=1)
    max_pages: int = Field(default=250, ge=1)
    max_render_pages: int = Field(default=12, ge=0)
    max_pixels: int = Field(default=40_000_000, ge=1)
    max_image_pixels: int = Field(default=40_000_000, ge=1)
    max_asset_bytes: int = Field(default=500_000_000, ge=1)
    workers: int = Field(default=2, ge=1, le=8)
    max_pdfs_per_state: int = Field(default=8, ge=1, le=100)
    crawl_pages: int = Field(default=6, ge=0, le=100)
    refresh: bool = False
    detect_boundaries: bool = True
    ocr: bool = False
    max_tiles_per_page: int = Field(default=16, ge=1, le=64)


class Manifest(Record):
    schema_version: Literal[1] = 1
    generated_at: str
    run_id: str
    source_revision: str
    requested_jurisdictions: list[str]
    options: Options
    documents: list[Document]
    reviews: list[Review]


class NormalizedRegion(Record):
    bbox_uv: tuple[float, float, float, float]
    bbox_mm_nominal: tuple[float, float, float, float]
    text: str
    evidence_page_bbox: tuple[float, float, float, float]


class BoundaryCandidate(Record):
    candidate_id: str
    page_number: int
    method: Literal["image_placement", "vector_rectangle", "contour"]
    page_bbox: tuple[float, float, float, float]
    page_corners: list[tuple[float, float]]
    aspect_ratio: float
    aspect_error: float
    score: float = Field(ge=0, le=1)
    crop_path: str
    text_regions: list[NormalizedRegion]
    warnings: list[str]
    review_status: Literal["unreviewed"] = "unreviewed"
    nominal_width_mm: float = 85.60
    nominal_height_mm: float = 53.98
    metric_accuracy_mm: None = None
    physical_calibration: Literal["none"] = "none"
