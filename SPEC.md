# Cadastre state ID reference library

## Purpose

Build a repeatable public-source reference collection for all 50 US states and DC.
The public deliverable is code, schemas, citation metadata, and reviewed normalized
geometry. A private vault retains original evidence and visual reference derivatives.
The harvesting job produces inspectable topology proposals and a separately reviewed
cohort interchange. It is not a document-authenticity verdict.

## Discovery and transport

* `seeds.py` maps exactly 51 jurisdictions to official entry points and includes direct
  historical and recent PDF leads. A seed is not a claim of current design.
* Without credentials, bounded official-page traversal follows relevant links using an
  HTML parser. No browser, JavaScript execution, or autonomous model loop is used.
* Serper or Brave credentials enable four fixed queries per selected jurisdiction.
  Provider requests are serialized with at least 1.1 seconds between requests.
* HTTPS `.gov` hosts are accepted; a small explicit list permits official legacy hosts.
  Redirects receive the same policy and public-address DNS checks. Requested candidates
  are checked against their origin's robots policy. Disallowed sources become gaps.
* Transport uses HTTPX 0.28.1, HTTP/2, 20-second operation timeouts, a 90-second download
  deadline, at most 15 concurrent requests and two per host, six redirect hops, and up
  to three attempts for 429/selected server errors. Read failures are retained for retry
  on the next run.
* PDF signatures are checked across chunk boundaries within the first 1024 bytes.
  Streamed files must be 25,000 through 36,700,160 bytes. Partial downloads are removed.

## Extraction and metrology

PyMuPDF 2.0 handles PDF text, images, and rendering in a process pool (default two workers,
maximum eight). OpenCV handles finite contour analysis and perspective mapping. Exact
resolved Python dependencies are committed in `uv.lock`.

1. Preserve original PDF bytes, source/final URLs, retrieval time, publisher host,
   inferred publisher jurisdiction, discovery jurisdiction, SHA-256, and HTTP validators.
2. Read native text and classify relevance using independent feature categories with
   token boundaries and normalized variants. Insufficient evidence is quarantined,
   not deleted. A relevance score never means credential authenticity.
3. Extract placed raster objects once per document xref, retaining compressed raw streams,
   soft-mask streams, object dictionaries, image formats, dimensions, and every placement
   rectangle and affine transform. Original PDFs preserve additional resource dependencies.
   Raw streams require their PDF dictionaries and may not be standalone image files.
4. Record text block coordinates, page MediaBox/CropBox, rotation, PDF-to-MuPDF transform,
   and display rotation matrix. Text and topology coordinates are unrotated MuPDF points.
   Full-page plates retain display rotation.
5. Rank pages using feature categories, security headings, and raster presence. Optional
   local Tesseract OCR processes ranked raster-bearing pages at at most six million pixels
   and 45 seconds per page. Keep raw TSV, coordinate-mapped lines, confidence, and OCR
   provenance. Native text and OCR observations remain distinguishable. OCR errors cannot
   become runtime rules automatically.
6. Retain source text observations containing security-feature terms and source table
   rows/cell geometry. Tables are extracted on selected security pages.
7. Render selected pages at 600 DPI (configurable 72-600). Oversized pages are tiled with
   explicit pixel origins and display clips, up to 16 tiles. Each tile is bounded by the
   pixel budget. Record every skipped page and reason. Thumbnails are separately bounded.
8. Propose boundaries from raster placements, vector rectangles, and quadrilateral contours.
   Rank by method and deviation from ID-1 aspect ratio; deduplicate overlapping proposals.
   Scores are heuristics, not probabilities. Keep up to 12 proposals per selected page.
9. Render perspective crops from the composed PDF page, preserving visible overlays.
   Map contained native/OCR text regions through the same homography into the unit square.
   External callouts stay external. Reference nominal coordinates to 85.60 x 53.98 mm,
   swapping dimensions for portrait. No physical accuracy is inferred from these dimensions.

Default per-PDF limits: 250 source pages, 12 selected rendering/detection/OCR pages,
40 million pixels per rendered tile and decoded image, 500 MB of written derivatives.
Raster-only or hybrid pages beyond the selection budget remain explicitly unprocessed.
No dewatermarking, hallucinated detail, inferred UV response, or synthetic specimen generation.

## Provenance, persistence, and review

All library paths are relative. Downloads and extraction receipts are hash checked before
reuse. Extractor source code, relevant options, and library versions determine the extraction
fingerprint. Changed source bytes or extractor inputs cause a new extraction. Unchanged
downloads can reuse extraction after a refresh. A single coordinator writes manifests
atomically and holds an exclusive output-directory lock.

`manifest.json` inventories current source versions and their assets. `runs/` preserves
candidate and outcome ledgers. Coverage always includes 51 rows; source discovery,
extraction, and accepted depicted-state coverage are separate facts. Partial runs expose
gaps instead of silently claiming completeness.

`reviews.json` binds a visual asset and source hash to a depicted jurisdiction, credential
type, design generation, side, reviewer, timestamp, and evidence. Review decisions are
separate from immutable extraction observations. `cohorts.json` adds reviewed zones and
modality-specific feature observations; export requires accepted visual evidence bindings.

## Runtime contract

`pulse_state_catalog_v1.json` is an interchange bundle of reviewed cohorts. It contains no
automatic authenticity rejection rules. An empty cohort list explicitly means review is
incomplete. No size guarantee is asserted until populated and measured.

The routing helper returns a candidate set. IIN, document type, and issue date are untrusted
barcode claims. DAJ describes the cardholder address jurisdiction, not the issuer. Date
overlaps, unknown boundaries, replacements, and design exceptions must preserve ambiguity.
Adult/under-21 layout is not inferred solely from age arithmetic. Runtime integration and
physical-card qualification are separate downstream work.

## Job and publication

GitHub Actions validates lint, formatting, strict application types, behavioral tests,
generated JSON schemas, and package build. A separate weekly/manual job restores the last
published snapshot, harvests all 51 jurisdictions with local OCR, rehashes the result,
exports reviewed cohorts, commits allowlisted metadata, and publishes a private immutable
snapshot through an authenticated Worker into private R2. There are no visual GitHub
releases or Actions artifacts. Search API keys are optional repository secrets; the vault
ingestion key is required. Private failure ledgers stay in the snapshot. Source media,
OCR text, seals, font outlines and raster derivatives never enter public static artifacts.
See `docs/publication.md` for transport, visual access and manual authorization boundaries.

## Acceptance

* Mechanical tests exercise transport limits, raw stream/mask preservation, repeated image
  placements, rotations, normalization, OCR boundaries, cache integrity, and routing ambiguity.
  Synthetic test inputs are not credential qualification evidence.
* Live collection proves only the sources, pages, and assets named in a particular manifest.
  Inspect real specimens visually before accepting any crop or cohort annotation.
* A 51-jurisdiction job configuration does not imply 51 reviewed state designs or all active
  revisions. Coverage gaps and unresolved sources remain visible in every publication.
