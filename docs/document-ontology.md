# Document ontology and extraction

Status: working design, version 0.1, 2026-10-26. Source classification is active
again after the ID-1 and WebP release. This document defines the next bounded
delivery; it does not claim that the corpus has already been classified or its
claims extracted.

## Purpose

Turn retained government publications into source-backed answers to questions
such as: which design does a passage describe, which features does it identify,
how does the source instruct an examiner to inspect them, and which conditions
limit that advice? Issuance requirements and acceptance policies are useful
knowledge, but must not become credential-security assertions by association.

## Audited starting point

The preserved source register contains 599 byte identities: 584 retained and 15
missing originals. Retained media comprise 177 PDFs, 117 HTML documents, and 290
original images. These are not 584 interchangeable guidance publications.

The PDFs contain 4,074 pages; 4,001 have native text. All 177 PDF source hashes
and native-packet source/page identities were checked in the resumed audit.
There are 73 textless pages in 21 PDFs, including two entirely image-only PDFs.
HTML native packets have not yet been produced.

Only 63 PDFs have provisional classifications: 33 classified, 23 mixed, six
needing review, and one incorrectly labeled unreadable. Those records contain
91 sections and 302 exact page/block/quote evidence links. The links validate;
the interpretations remain provisional. The two-page PDF labeled unreadable is
parseable and unencrypted, with raster content and no native text. Its proper
processing state is image-only, visual review pending.

Large sources include driver manuals, commercial-driver handbooks and an
inspection-business manual. Sending every page through a security-feature
extractor would recreate the original scope error.

Local evidence: `output/domain-classification/ontology-audit-2026-10-26.json`.
Its SHA-256 is `86e6c94d7d481ddce75064fac26473622398301f1d9cad061e30dcd48bd00d52`.
The audit preserves the earlier register and partial classifications.

## Two vocabularies with separate authority

Publication roles describe why a source was written. Our repository owns those
labels: technical standard, legislation/regulation, issuer design reference,
examiner/retailer training, issuance guidance, design announcement, operational
manual, and unresolved. A publication can have multiple roles and mixed sections.
These are engineering labels, not an AAMVA publication taxonomy.

Credential concepts use an edition-specific standards crosswalk. The current
official reference is the **2026 AAMVA DL/ID Card Design Standard, Version 1.0,
October 2026**. The [official publications page][publications] links the
[2026 PDF][cds2026]. Older topic pages can still link earlier editions.

| Concept to normalize | AAMVA 2026 reference | Extraction boundary |
| --- | --- | --- |
| Human-readable fields | Section 4, Tables 1-2 | Field definition and required/optional status retain edition and context. |
| Card format, orientation and layout | Annex A, especially A.3 and A.6-A.7 | Standard zones do not establish measured positions on a particular specimen. |
| Physical security | Annex B, especially B.3.2 and B.4.2 | Record security family independently from inspection level and modality. |
| Document threats | B.3.3 and Annex C | A threat description is not evidence that a particular credential has a feature. |
| PDF417 structure and elements | Annex D, especially D.12.5 | Preserve edition and identifier; do not infer an issuer or design from an address field. |
| Other machine-readable technologies | Annexes F-J | Applicability requires source support; never assume every credential uses them. |
| Production quality and durability | Section 5 and Annex E | Production requirements remain distinct from camera-observable properties. |

Within physical security, preserve the four family distinctions: card-body
construction, resistance to reproduction, security inks/pigments, and protection
of personalized information. Keep inspection levels separate: unaided inspection,
inspection using instruments, and forensic examination. A feature can require a
particular modality without that modality defining its security family.

Retain [2025][cds2025] and [2020][cds2020] authority references for legacy material.
A mapping to the 2026 vocabulary does not assert compliance with 2026 requirements
or retroactively impose them on an older design. Federal credentials need their
own applicable authorities; AAMVA is not a universal federal-ID ontology.

## Entities and relationships

Use versioned JSON records and stable identifiers first. A graph database or RDF
stack is not required to represent these relationships.

1. **Source publication** identifies immutable bytes, URL aliases, publisher,
   media type, stated edition/date and document roles. Retrieval dates and HTTP
   modification dates remain separate from publication dates. Publisher location
   does not identify the jurisdiction depicted in an example.
2. **Section** belongs to a source and has an explicit evidence scope. It carries
   one or more knowledge domains, such as design/security, inspection procedure,
   acceptance policy, issuance administration or unrelated operational material.
   Classification can abstain or identify a mixed section.
3. **Credential subject/design** identifies the issuer, credential family, design
   or revision, variant and side only as far as the evidence supports them. Unknown
   values remain unknown. A source can discuss multiple designs and jurisdictions.
4. **Statement** records a typed assertion, instruction or condition about that
   subject. A source requirement, source recommendation, descriptive assertion
   and illustrative example remain distinct. A negative assertion needs explicit
   evidence; omission is not absence.
5. **Evidence anchor** binds a statement or classification to exact retained source
   content. PDF evidence includes source hash, physical PDF page, block/span IDs
   and quote. HTML evidence will need a native node/section locator and exact text.
   Source coordinates are derived from native records, never supplied by a model.
6. **Authority mapping** links a normalized concept to the issuing standard,
   edition and clause. It records the mapping basis and unresolved questions.
   Categorization is not proof that the issuer adopted a standard's requirement.

Statements also retain their scope and conditions: holder category, effective
wording/date precision, inspection modality, exceptions and design applicability.
Source assertions and reviewed interpretations have separate statuses. Conflicting
statements remain separately cited; recency alone does not silently resolve them.

## Domain-specific extraction

| Section domain | Structured output | Must not be inferred |
| --- | --- | --- |
| Credential design/security | Feature concept, description, source-stated location, inspection modality, design applicability | Exact card coordinates or presence on other revisions |
| Inspection procedure | Action, target, expected observation, equipment and conditions | A tested detector or automatic rejection rule |
| Acceptance policy | Credential category, permitted context, conditions, exceptions and stated period | Universal legal acceptance outside the source's scope |
| Issuance administration | Application/renewal process, required evidence, temporary/permanent document distinctions | An authenticity test for the issued card |
| Technical standard | Edition-specific requirement, concept and clause reference | Adoption by an issuer without supporting evidence |
| Other/unresolved | Classification evidence and reason for exclusion or review | Security facts generated merely because an ID illustration appears nearby |

For example, the Illinois central-issuance brochure contains both issuance advice
and design/security descriptions, plus historical travel advice. The Indiana
security flyer discusses different designs on different pages. The Arkansas
retailer brochure mixes age-verification policy and tobacco-business operations.
Their section boundaries govern extraction; their filenames do not.

## Reuse and narrowly defined gaps

Reuse the retained native PyMuPDF extraction and existing `PageSemantics`,
`SourceLine`, `LayoutSection`, and `SourceObservation` contracts. Existing
`semantic_review` already checks exact quotes and image/section scope. Its current
claim model requires an image target; text-only laws, policies and issuance
instructions need an explicit text-section target, not a fabricated image link.

The preserved register packets lack page rotation/transformation metadata.
Twenty-six rotated pages occur in five PDFs. Quote/page/block anchors remain
useful, but geometry joins must use the existing unrotated MuPDF coordinate
contracts before any figure or card association is accepted. Do not silently
rewrite the earlier evidence packets.

The existing keyword feature matcher can propose review candidates. It is not a
document classifier, ontology or source-grounded fact extractor. Existing
accepted-cohort contracts remain downstream of this knowledge layer.

## Strict Pydantic contracts and private storage

`knowledge.py` implements the ontology as Pydantic BaseModels through the existing
`Record` base. Validation is strict, extra fields are forbidden, records are
frozen, and collections are immutable tuples. JSON arrays are admitted as tuples;
scalar strings, booleans and floats cannot masquerade as integer page numbers,
counts or inspection levels. Nested model instances are revalidated as well.

`DocumentKnowledge` checks unique identifiers, matching source hashes, physical
page bounds, classified section domains, evidence references and subject scope.
Statement payloads use a discriminated union for design, inspection, acceptance,
issuance and standard requirements. Date values preserve year/month/day precision
and must be valid calendar dates. Conditions and exceptions remain explicit.
Thermal inspection is an explicit modality for the retained Missouri temporary
document's warming instruction; it does not imply a camera can perform the test.

Extraction backends must use `load_knowledge()` to admit bounded JSON. For PDFs,
`load_grounded_pdf_knowledge()` additionally checks exact quoted text against the
typed native packet. Both reject duplicate JSON fields before a last-value-wins
parser can discard contradictory input. HTML node/text grounding still needs its
native extraction implementation; valid HTML anchor types alone do not prove a quote.

`knowledge_store.prepare_artifacts()` then independently re-extracts native text,
block identifiers, bounding boxes and page dimensions from the retained PDF. A
fabricated packet cannot substantiate a claim merely by repeating a genuine
source hash. Validation precedes writing any artifacts.

The canonical artifact store is the existing private R2 vault. Its local working
mirror is ignored `output/knowledge/`. Keys are content addressed:

| Content | Private R2 key |
| --- | --- |
| Original PDF bytes | `snapshots/knowledge/v1/sources/{source_sha256}.pdf` |
| Native text and blocks | `snapshots/knowledge/v1/native-packets/{packet_sha256}.json` |
| Validated structured statements | `snapshots/knowledge/v1/documents/{record_sha256}.json` |
| Metadata-only registry projection | `snapshots/knowledge/v1/registry-projections/{projection_sha256}.json` |

`Artifact`, `RegistryProjection`, `PreparedManifest` and `KnowledgeIndex` are also
strict BaseModels. They check key/hash/kind/source bindings, counts, immutable
artifact membership and unique current source identities. Preparation never
activates the private `indexes/knowledge.json` pointer. Upload and hash readback
must finish before that pointer is activated. These paths add no anonymous raw
source or knowledge API.

D1 will hold the query registry, active versions and review decisions; this
delivery prepares its metadata projection without applying a production migration.
Vectorize will hold a later retrieval projection that refers back to records and
evidence. It will not be the canonical store for source text or extracted facts.
Git retains code, generated schemas and aggregate delivery receipts, while source
publications, full quotes and extraction artifacts stay private.

Schemas for document knowledge, native PDF packets, prepared storage manifests
and the private registry index are generated by `scripts/export_schemas.py`.
CI's existing `--check` step fails if the models and committed schemas drift.
Structural and quote validation do not establish the truth of an interpretation;
new extracted statements remain explicitly unreviewed.

## Remaining delivery and acceptance

The remaining implementation completes an edition-specific standards crosswalk
and corpus classification register with explicit unresolved items. Keep classification separate from native
parsing success and distinguish image-only PDFs from corrupt or inaccessible files.

Its checks must reject invented evidence, mismatched source hashes, out-of-range
pages, cross-section/design leakage and unsupported standard mappings. Every
source is accounted for, including the 15 missing originals and the unprocessed
HTML/image routes. Mixed publications stay mixed; a single title match cannot
label an entire manual as credential-security guidance.

Only then run the appropriate fact extractor for each classified section. A
retrieval unit contains a typed claim or coherent passage together with its
source anchors, domain, subject, edition/period, conditions and review state.
It must not merge statements across designs or strip qualifiers to meet a fixed
character count. Embeddings index these records later; they do not replace them.

No new document-processing framework, OCR pass, source-harvesting sweep, vector
database or website change is part of this ontology delivery.

[publications]: https://www.aamva.org/publications-news/best-practices-standards/best-practices
[cds2026]: https://www.aamva.org/getmedia/feab821e-baa5-4524-b865-3eb172b51acd/2026-DLID-Card-Design-Standard.pdf
[cds2025]: https://www.aamva.org/getmedia/81af105d-8b1b-45e1-aa46-f1800a259ed1/AAMVADLIDCardDesignStandard2025.pdf
[cds2020]: https://www.aamva.org/getmedia/99ac7057-0f4d-4461-b0a2-3a5532e1b35c/AAMVA-2020-DLID-Card-Design-Standard.pdf
