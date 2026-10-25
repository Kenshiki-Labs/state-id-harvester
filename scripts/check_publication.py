"""Reject private specimen media and embedded source resources in public trees."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class PublicRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(PublicRecord):
    title: str = Field(min_length=1, max_length=240, pattern=r"^[^\x00-\x1f<>]+$")
    url: str = Field(max_length=4096)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    retrieved_at: str = Field(max_length=64)
    publisher_host: str = Field(max_length=253)
    publisher_jurisdiction: str | None = Field(pattern=r"^(?:[A-Z]{2}|US_FED)$")
    discovery_jurisdiction: str = Field(pattern=r"^(?:[A-Z]{2}|US_FED)$")
    credential_format: str = Field(default="ID1", pattern=r"^(?:ID1|unclassified)$")
    relevance: str = Field(pattern=r"^(candidate|quarantined)$")
    review_status: str = Field(pattern=r"^(unreviewed|accepted|rejected)$")
    page_count: int = Field(ge=0)

    @field_validator("url")
    @classmethod
    def credential_free_https(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Citation URL must be credential-free HTTPS")
        return value


class Counts(PublicRecord):
    sources: int = Field(ge=0)
    relevant_sources: int = Field(ge=0)
    embedded_images: int = Field(ge=0)
    rendered_pages: int = Field(ge=0)
    crop_candidates: int = Field(ge=0)
    accepted_cohorts: int = Field(ge=0)


class Stats(Counts):
    jurisdictions: int = Field(ge=0, le=51)
    jurisdictions_with_sources: int = Field(ge=0, le=51)
    jurisdictions_with_accepted_cohorts: int = Field(ge=0, le=51)


class Jurisdiction(PublicRecord):
    code: str = Field(pattern=r"^[A-Z]{2}$")
    name: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z ]+$")
    status: str = Field(pattern=r"^(sources_available|gap)$")
    review_status: str = Field(pattern=r"^(reviewed|unreviewed)$")
    counts: Counts
    fetch_failures: int = Field(ge=0)
    extraction_failures: int = Field(ge=0)
    sources: list[Citation]


class FederalCollection(Jurisdiction):
    code: str = Field(pattern=r"^US_FED$")
    credential_format: str = Field(pattern=r"^unclassified$")


class Catalog(PublicRecord):
    schema_version: int = Field(ge=1, le=1)
    generated_at: str = Field(max_length=64)
    library_run_id: str = Field(max_length=128)
    stats: Stats
    jurisdictions: list[Jurisdiction] = Field(min_length=51, max_length=51)
    federal: FederalCollection | None = None


class CitationManifest(PublicRecord):
    schema_version: int = Field(ge=1, le=1)
    generated_at: str = Field(max_length=64)
    library_run_id: str = Field(max_length=128)
    documents: list[Citation]


class Zone(PublicRecord):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[^\x00-\x1f<>]+$")
    bbox_uv: tuple[float, float, float, float]
    geometry_basis: str = Field(pattern=r"^(reviewed_specimen|physical_calibration)$")
    measured_error_mm: float | None = Field(gt=0)

    @field_validator("bbox_uv")
    @classmethod
    def normalized(
        cls, value: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = value
        if not 0 <= x0 < x1 <= 1 or not 0 <= y0 < y1 <= 1:
            raise ValueError("Invalid normalized geometry")
        return value


class GeometryCohort(PublicRecord):
    cohort_id: str = Field(pattern=r"^[A-Z0-9_]+$", max_length=128)
    jurisdiction: str = Field(pattern=r"^[A-Z]{2}$")
    credential_type: str = Field(pattern=r"^(driver_license|identification_card|learner_permit)$")
    orientation: str = Field(pattern=r"^(horizontal|vertical)$")
    iins: list[str]
    issue_date_start: str | None = Field(max_length=10)
    issue_date_end: str | None = Field(max_length=10)
    design_generation: str = Field(min_length=1, max_length=128, pattern=r"^[^\x00-\x1f<>]+$")
    review_status: str = Field(pattern="^accepted$")
    source_sha256s: list[str]
    zones: list[Zone]


class GeometryBundle(PublicRecord):
    schema_version: int = Field(ge=1, le=1)
    coordinate_convention: str = Field(max_length=128)
    routing: str = Field(max_length=128)
    cohorts: list[GeometryCohort]


BLOCKED_SUFFIXES = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".tif",
    ".tiff",
    ".bmp",
    ".jp2",
    ".jbig2",
    ".ppm",
    ".pbm",
    ".pgm",
    ".raw",
    ".bin",
    ".tar",
    ".gz",
    ".zip",
    ".tsv",
    ".otf",
    ".ttf",
    ".woff",
    ".woff2",
}
ALLOWED_SUFFIXES = {".json", ".md", ".txt", ".svg", ".xml", ".html", ".css", ".js", ".map"}
SIGNATURES = (b"%PDF-", b"\x89PNG\r\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")
SOURCE_KEYS = re.compile(
    r'"(?:raw_text|ocr_text|image_data|raw_stream|font_outlines|text_blocks|data_uri)"\s*:',
    re.IGNORECASE,
)


def validate_public_json(path: Path, content: str) -> None:
    """Only known metadata shapes may cross the public boundary."""
    from pydantic import TypeAdapter

    data = json.loads(content)
    if "schemas" in path.parts and path.name.endswith(".schema.json"):
        if not isinstance(data, dict) or not ({"type", "$ref", "anyOf"} & data.keys()):
            raise ValueError("Invalid public JSON schema")
        return
    shapes = {
        "catalog.json": Catalog,
        "cohorts.json": GeometryBundle,
        "manifest.json": CitationManifest,
        "coverage.json": list[Jurisdiction],
        "summary.json": Stats,
        "federal.json": FederalCollection,
    }
    if path.name not in shapes:
        raise ValueError("Unrecognized public JSON payload")
    TypeAdapter(shapes[path.name]).validate_python(data)


def normalized_uris(content: str) -> str:
    # CSS escapes and HTML entities otherwise hide data: from a byte substring guard.
    decoded = re.sub(
        r"\\([0-9a-fA-F]{1,6})\s?",
        lambda match: chr(min(int(match[1], 16), 0x10FFFF)),
        content,
    )
    return unquote(html.unescape(decoded)).replace("\\\n", "")


def inspect_plaintext(relative: Path, decoded: str) -> list[str]:
    if relative.suffix.lower() == ".md":
        return [] if relative.name == "coverage.md" else [f"Unapproved public Markdown: {relative}"]
    if relative.name != "robots.txt":
        return [f"Unapproved public plaintext: {relative}"]
    for line in decoded.splitlines():
        if line.strip() and not re.fullmatch(
            r"(?:User-agent|Allow|Disallow|Sitemap|Crawl-delay):[^\r\n]*", line.strip(), re.I
        ):
            return [f"Unapproved public plaintext: {relative}"]
    return []


def inspect_json(relative: Path, decoded: str) -> list[str]:
    errors = []
    if "schemas" not in relative.parts and SOURCE_KEYS.search(decoded):
        errors.append(f"Raw extraction payload in public JSON: {relative}")
    try:
        validate_public_json(relative, decoded)
    except (ValueError, ValidationError):
        errors.append(f"Unapproved or malformed public JSON payload: {relative}")
    return errors


def inspect_svg_attributes(element: ET.Element) -> bool:
    return any(
        key.rsplit("}", 1)[-1].lower().startswith("on")
        or "href" in key.lower()
        or "url(" in value.lower()
        for key, value in element.attrib.items()
    )


def inspect_svg(relative: Path, decoded: str) -> list[str]:
    errors = []
    try:
        svg = ET.fromstring(decoded)
    except ET.ParseError:
        return [f"Malformed SVG: {relative}"]
    if svg.attrib.get("data-cadastre-diagram") not in {"independent", "reviewed-geometry"}:
        errors.append(f"SVG lacks independent/reviewed geometry declaration: {relative}")
    for element in svg.iter():
        if element.tag.rsplit("}", 1)[-1].lower() in {
            "image",
            "foreignobject",
            "script",
            "text",
            "style",
        }:
            errors.append(f"SVG contains embedded media, text or executable element: {relative}")
        if inspect_svg_attributes(element):
            errors.append(f"SVG contains external or active references: {relative}")
    return errors


def inspect_text_resource(path: Path, relative: Path) -> list[str]:
    content = path.read_bytes()
    errors = []
    if any(signature in content for signature in SIGNATURES):
        errors.append(f"Embedded source-media signature: {relative}")
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError:
        return [*errors, f"Binary resource masquerading as public text: {relative}"]
    if "\x00" in decoded:
        errors.append(f"NUL bytes in public text: {relative}")
    if re.search(
        r"data\s*:\s*(?:image|application/(?:pdf|octet-stream))", normalized_uris(decoded), re.I
    ):
        errors.append(f"Embedded media data URI: {relative}")
    if path.suffix.lower() == ".html" and re.search(r"<\s*(?:img|picture|image)\b", decoded, re.I):
        errors.append(f"Raster delivery element in public HTML: {relative}")
    if path.suffix.lower() == ".css" and re.search(
        r"url\([^)]*\.(?:png|jpe?g|webp|gif|pdf)(?:[?'\"\s)]|$)",
        normalized_uris(decoded),
        re.I,
    ):
        errors.append(f"Raster resource in public CSS: {relative}")
    inspectors = {
        ".txt": inspect_plaintext,
        ".md": inspect_plaintext,
        ".json": inspect_json,
        ".svg": inspect_svg,
    }
    inspector = inspectors.get(path.suffix.lower())
    if inspector is not None:
        errors.extend(inspector(relative, decoded))
    return errors


def registered_brand_font(path: Path, relative: Path, bundled: bool) -> bool:
    if not bundled or relative.parts[0] != "_astro" or path.suffix != ".woff2":
        return False
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    source_fonts = Path("web/src/assets/fonts").glob("*.woff2")
    return checksum in {hashlib.sha256(font.read_bytes()).hexdigest() for font in source_fonts}


def inspect_public_tree(root: Path, *, bundled: bool = False) -> list[str]:
    errors = []
    if not root.is_dir():
        return [f"Missing public tree: {root}"]
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            errors.append(f"Public symlink: {relative}")
            continue
        if not path.is_file() or registered_brand_font(path, relative, bundled):
            continue
        if path.suffix.lower() in BLOCKED_SUFFIXES or (
            path.suffix.lower() not in ALLOWED_SUFFIXES
            and path.name not in {"_headers", "_redirects"}
        ):
            errors.append(f"Forbidden public asset type: {relative}")
            continue
        errors.extend(inspect_text_resource(path, relative))
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="*", type=Path, default=[Path("web/public"), Path("library")]
    )
    parser.add_argument(
        "--bundled", action="store_true", help="Allow bundled Astro brand WOFF2 fonts"
    )
    args = parser.parse_args()
    errors = [
        error for path in args.paths for error in inspect_public_tree(path, bundled=args.bundled)
    ]
    if errors:
        raise SystemExit("\n".join(errors))
    print("Public artifact guard passed")


if __name__ == "__main__":
    main()
