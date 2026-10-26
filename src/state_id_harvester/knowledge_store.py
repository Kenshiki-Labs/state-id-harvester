"""Prepare private, immutable knowledge artifacts; never publish a pointer or execute DDL."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal, Self

import pymupdf
from pydantic import Field, StringConstraints, field_validator, model_validator

from .knowledge import Digest, Index, KnowledgeRecord, PositiveInt, Role
from .knowledge_evidence import NativePdfPacket, load_grounded_pdf_knowledge
from .paths import contained_path, managed_path

MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_PACKET_BYTES = 32 * 1024 * 1024
MAX_RECORD_BYTES = 8 * 1024 * 1024
PREFIX = "snapshots/knowledge/v1"


ArtifactKind = Literal["sources", "native-packets", "documents", "registry-projections"]
Version = Annotated[int, Field(strict=True, ge=1, le=1)]
ObjectKey = Annotated[
    str,
    StringConstraints(
        pattern=r"^snapshots/knowledge/v1/(sources|native-packets|documents|registry-projections)/[a-f0-9]{64}\.(pdf|json)$"
    ),
]


class Artifact(KnowledgeRecord):
    schema_version: Version = 1
    kind: ArtifactKind
    key: ObjectKey
    sha256: Digest
    size_bytes: PositiveInt
    source_sha256: Digest

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        extension = "pdf" if self.kind == "sources" else "json"
        if self.key != f"{PREFIX}/{self.kind}/{self.sha256}.{extension}":
            raise ValueError("Artifact kind, key and hash differ")
        if self.kind == "sources" and self.sha256 != self.source_sha256:
            raise ValueError("Raw source artifact identity differs")
        limit = MAX_SOURCE_BYTES if self.kind == "sources" else MAX_PACKET_BYTES
        if self.kind == "documents":
            limit = MAX_RECORD_BYTES
        if self.size_bytes > limit:
            raise ValueError("Artifact exceeds its kind's size budget")
        return self


class RegistryProjection(KnowledgeRecord):
    schema_version: Version = 1
    source_sha256: Digest
    record_sha256: Digest
    source_key: ObjectKey
    native_packet_key: ObjectKey
    record_key: ObjectKey
    media_type: Literal["application/pdf"]
    processing: Literal["native_text", "image_only"]
    page_count: PositiveInt
    roles: Annotated[tuple[Role, ...], Field(min_length=1, max_length=8)]
    section_count: Index
    statement_count: Index
    review_status: Literal["unreviewed"] = "unreviewed"

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if self.source_key != f"{PREFIX}/sources/{self.source_sha256}.pdf":
            raise ValueError("Registry source key differs from source identity")
        if self.record_key != f"{PREFIX}/documents/{self.record_sha256}.json":
            raise ValueError("Registry record key differs from record identity")
        if not self.native_packet_key.startswith(f"{PREFIX}/native-packets/"):
            raise ValueError("Registry native packet key has the wrong kind")
        if not self.native_packet_key.endswith(".json"):
            raise ValueError("Registry native packet must be JSON")
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("Duplicate publication roles")
        return self


class PreparedManifest(KnowledgeRecord):
    schema_version: Version = 1
    source_sha256: Digest
    artifacts: Annotated[tuple[Artifact, ...], Field(min_length=4, max_length=4)]
    registry_projection: RegistryProjection
    pointer_key: Literal["indexes/knowledge.json"] = "indexes/knowledge.json"
    pointer_published: Literal[False] = False

    @field_validator("pointer_published", mode="before")
    @classmethod
    def strict_false(cls, value: object) -> object:
        if value is not False:
            raise ValueError("Preparation cannot publish a pointer")
        return value

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        kinds = ("sources", "native-packets", "documents", "registry-projections")
        if tuple(item.kind for item in self.artifacts) != kinds:
            raise ValueError("Manifest requires each artifact kind once in canonical order")
        if any(item.source_sha256 != self.source_sha256 for item in self.artifacts):
            raise ValueError("Manifest artifacts cross source identities")
        registry = self.registry_projection
        if registry.source_sha256 != self.source_sha256:
            raise ValueError("Registry and manifest source identities differ")
        if (registry.source_key, registry.native_packet_key, registry.record_key) != tuple(
            item.key for item in self.artifacts[:3]
        ):
            raise ValueError("Registry keys differ from manifest artifacts")
        projection = canonical_json(registry)
        if (self.artifacts[3].sha256, self.artifacts[3].size_bytes) != (
            digest(projection),
            len(projection),
        ):
            raise ValueError("Registry projection bytes differ from manifest binding")
        return self


class KnowledgeIndex(KnowledgeRecord):
    schema_version: Version = 1
    documents: Annotated[tuple[RegistryProjection, ...], Field(max_length=10000)]

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        identities = [item.source_sha256 for item in self.documents]
        if len(identities) != len(set(identities)):
            raise ValueError("Knowledge index contains duplicate source identities")
        return self


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: KnowledgeRecord) -> bytes:
    serialized = json.dumps(
        value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return (serialized + "\n").encode()


def checked_path(path: Path) -> Path:
    """Reject aliases before resolving; managed_path rejects escapes from permitted roots."""
    original = Path(path).absolute()
    if ".." in original.parts or any(part.is_symlink() for part in (original, *original.parents)):
        raise ValueError("Knowledge paths must not contain symlinks or parent traversal")
    return managed_path(original)


def bounded_read(path: Path, limit: int) -> bytes:
    path = checked_path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Invalid or oversized knowledge artifact")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Knowledge artifact exceeds admission budget")
    return data


def verify_native_pdf(source: bytes, packet: NativePdfPacket) -> None:
    """Re-extract every text block, including its identifier and geometry, from retained bytes."""
    if digest(source) != packet.source_sha256:
        raise ValueError("Raw PDF source hash mismatch")
    with pymupdf.open(stream=source, filetype="pdf") as document:
        if document.needs_pass or document.page_count != len(packet.pages):
            raise ValueError("PDF encryption or page count mismatch")
        text_bytes = 0
        for page, supplied in zip(document, packet.pages, strict=True):
            if (page.rect.width, page.rect.height) != (supplied.width_pt, supplied.height_pt):
                raise ValueError("Native packet page dimensions differ from PDF")
            actual = []
            for block in page.get_text("blocks"):
                if block[6] == 0 and block[4].strip():
                    text_bytes += len(block[4].encode())
                    if text_bytes > MAX_PACKET_BYTES:
                        raise ValueError("Native PDF text exceeds admission budget")
                    actual.append((int(block[5]), tuple(block[:4]), block[4]))
            claimed = [(block.block_id, block.bbox, block.text) for block in supplied.blocks]
            if actual != claimed:
                raise ValueError("Native packet blocks differ from actual PDF")


def immutable_write(root: Path, key: str, data: bytes) -> None:
    checked_path(root / key)
    path = contained_path(root, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        if bounded_read(path, len(data)) != data:
            raise ValueError("Immutable artifact collision") from None


def artifact(kind: ArtifactKind, data: bytes, source_hash: str) -> Artifact:
    sha = digest(data)
    extension = "pdf" if kind == "sources" else "json"
    return Artifact(
        kind=kind,
        key=f"{PREFIX}/{kind}/{sha}.{extension}",
        sha256=sha,
        size_bytes=len(data),
        source_sha256=source_hash,
    )


def prepare_artifacts(
    source_path: Path, packet_path: Path, record_path: Path, destination: Path
) -> PreparedManifest:
    """Validate all inputs before writing local mirrors of future private R2 keys.

    The returned manifest and registry projection are inert upload inputs. They do
    not modify ``indexes/knowledge.json`` or grant any public access.
    """
    root = checked_path(destination)
    source = bounded_read(source_path, MAX_SOURCE_BYTES)
    packet_bytes = bounded_read(packet_path, MAX_PACKET_BYTES)
    record_bytes = bounded_read(record_path, MAX_RECORD_BYTES)
    record = load_grounded_pdf_knowledge(record_bytes, packet_bytes)
    packet = NativePdfPacket.model_validate_json(packet_bytes)
    verify_native_pdf(source, packet)
    has_text = any(page.blocks for page in packet.pages)
    expected_processing: Literal["native_text", "image_only"] = (
        "native_text" if has_text else "image_only"
    )
    if record.source.processing != expected_processing or record.source.availability != "retained":
        raise ValueError("Knowledge processing state differs from retained PDF")
    source_hash = digest(source)
    payloads: tuple[tuple[ArtifactKind, bytes], ...] = (
        ("sources", source),
        ("native-packets", canonical_json(packet)),
        ("documents", canonical_json(record)),
    )
    artifacts = tuple(artifact(kind, data, source_hash) for kind, data in payloads)
    registry = RegistryProjection(
        source_sha256=source_hash,
        record_sha256=artifacts[2].sha256,
        source_key=artifacts[0].key,
        native_packet_key=artifacts[1].key,
        record_key=artifacts[2].key,
        media_type="application/pdf",
        processing=expected_processing,
        page_count=len(packet.pages),
        roles=record.source.roles,
        section_count=len(record.sections),
        statement_count=len(record.statements),
    )
    projection = canonical_json(registry)
    registry_artifact = artifact("registry-projections", projection, source_hash)
    manifest = PreparedManifest(
        source_sha256=source_hash,
        artifacts=(*artifacts, registry_artifact),
        registry_projection=registry,
    )
    # All admission checks have passed. Existing differing bytes are never overwritten.
    for entry, (_, data) in zip(artifacts, payloads, strict=True):
        immutable_write(root, entry.key, data)
    immutable_write(root, registry_artifact.key, projection)
    manifest_data = canonical_json(manifest)
    immutable_write(root, f"manifests/{digest(manifest_data)}.json", manifest_data)
    return manifest
