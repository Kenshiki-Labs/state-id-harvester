# Separate federal credential collection

`US_FED` is a collection code, not a 52nd state. State/DC coverage remains exactly
51 rows. Run the federal collector independently so it preserves the state manifest:

```sh
uv run state-id-harvester harvest --federal --output output/federal --ocr
uv run state-id-harvester verify --output output/federal
uv run python scripts/build_public_catalog.py
```

The public catalog's `federal` subsection and `library/federal.json` contain citation
metadata and separate counts. Federal PDFs, extracted images, page plates, text and
original vector resources remain private under the same vault policy as state sources.
The private snapshot packager retains the nested federal collection as well as state data.

## Verified seed sources

The first live run downloaded all five PDFs below with no fetch or extraction failures.
Hash and byte-count verification passed. The source inventory is 372 pages; the bounded
extractor produced 303 native images and 30 rendered pages. These are collection counts,
not a count of accepted credential designs. Three documents passed the existing security
term relevance filter and two remain quarantined for review. A normative reference such
as NIST FIPS 201-3 is not itself a specimen or a runtime template.

| Source | Pages | SHA-256 |
| --- | ---: | --- |
| [NIST FIPS 201-3](https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.201-3.pdf) | 133 | `3d305e90719e373963d3753d7d07d648361e35099e95e551763962e26456e73e` |
| [CBP Carrier Information Guide](https://www.cbp.gov/sites/default/files/assets/documents/2023-Nov/Carrier%20Information%20Guide%20ENGLISH.pdf) | 92 | `eb8899b58c24c43f1c88b9efc66a6d342d7e79d80000001ac62cc7f91ace5bb0` |
| [USCIS Green Card comparison](https://www.uscis.gov/sites/default/files/document/guides/GreenCard_Comparison_EN.PDF) | 1 | `ef78d2f6e4d4fceb48b7a6183f91b61b8f00a52a8ec307ff0dbd29be24020c8a` |
| [USCIS EAD comparison](https://www.uscis.gov/sites/default/files/document/guides/EAD_Comparison_EN.pdf) | 1 | `7138164845e5a2c4cf04cf0a8a920e27577223b6236091258a2faa97c4c08d6c` |
| [TxDMV fraudulent-document recognition guide](https://www.txdmv.gov/sites/default/files/body-files/FDR_Level_I_Job_Aid_2018.pdf) | 145 | `2659254d52c84ac2602d6a4d104a4c80ddd8fbec9e014a4086714f33e990f5d1` |

The initial run identifier is `2026-10-25T231905.862718Z-0b8a7797`; its private
`manifest.json`, `events.json`, and `federal-coverage.json` retain exact provenance.
The CBP URL containing `Guide%20-%20English.pdf` returned 404; the `Guide%20ENGLISH.pdf`
URL above returned a PDF. Both USCIS Green Card `.PDF` and `.PDF.pdf` endpoints returned
PDF headers; the collector uses `.PDF`. No alternate-host mirrors or access bypasses
were used. Texas remains the publisher jurisdiction of its guide even when that guide
is discovered for the federal collection.

## Format and evidence boundaries

FIPS 201-3 is a PIV standard. Its normative and optional topographic elements cannot be
assumed to describe every DoD CAC, USID card or agency credential. See the standard's
[applicability and physical-characteristics sections](https://pages.nist.gov/FIPS201/FIPS201.html).
This project does not infer a fixed count of active federal templates from the source list.

Mixed guides can include passport books, cards, visas and other document formats. Every
federal source currently declares `credential_format: unclassified`. The CLI disables
ID-1 boundary normalization, and the extractor independently blocks ID-1 proposals for
`US_FED` even if a caller requests boundary detection. No TD3 passport page is scaled to
an ID-1 card, and no millimeter-accuracy claim is derived from a brochure image. There
are currently zero accepted federal cohorts and zero federal ID-1 crop proposals.

NFC and cryptographic capabilities require family-specific evidence. Collection of an
EAD or Green Card comparison sheet does not establish an ICAO passport chip, BAC/PACE,
an EF.SOD, or a State Department certificate chain for that credential. PIV authentication
and eMRTD authentication are separate protocols; a broadly labeled federal bucket cannot
select either. Likewise, MRZ formats and numbering rules must be sourced per family and
version rather than assumed across all documents in a carrier guide.

Source-backed facts, normative geometry and tested mathematical algorithms can be
published with their evidence and assumptions. Physical capture experiments are required
for camera error rates, optical-feature detection rates and measured metric tolerances;
they are not a blanket prerequisite for publishing a cited fact or a mathematical method.

An agency hosting a PDF does not establish that all embedded content is government-
authored or unrestricted for every use. This project makes no blanket redistribution or
legal-immunity claim for federal imagery. Original visuals remain private and external
delivery follows the reference-use authorization and source-rights review described in
[the publication policy](publication.md).
