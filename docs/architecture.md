# Architecture alignment

Cadastre follows the separation of capability, host, presentation, and policy used by
`kenshiki-sdks` (APP-ARCH-001) and `kenshiki-gateway`. This is a standalone product with
its own deployment and data bindings. Alignment does not migrate or modify either system.

| Boundary | Responsibility |
| --- | --- |
| Python extraction core | Reproducible transport, parsing, geometry and evidence observations |
| Review and interchange | Accepted source/asset bindings, reviewed topology and ambiguous candidate routing |
| Public exporter | Explicit field allowlist; citations, counts, schemas and normalized geometry |
| Astro presentation | Static public pages with small interactive islands consuming supplied state |
| Cloudflare Worker host | Anonymous indexed reference delivery, request validation, protected-operation authorization and audit |
| Isolated D1 / private R2 | Application and key state / private media, snapshots and indexes |

The presentation layer displays supplied observations and forwards typed events. Domain
rules, review decisions, privileged fetches and authorization stay outside components.
Storage and platform mechanisms are isolated behind host interfaces rather than imported
into the extraction core or a renderer. Operator secrets never become frontend build
inputs. Original source media does not enter Astro's public assets or its build graph. The browser obtains the public reference
catalog and indexed, visibly marked PNGs through the Worker BFF; the private R2 bucket
has no public URL.

Typed observations preserve source hash, asset hash, page and extraction lineage.
Normalization yields nominal unit-square coordinates. Evidence is evaluated per claim:
sourced topology, normative formats, and tested computations do not require a physical-card
collection to publish. Claimed measurement error and detection performance require ground
truth and evaluation appropriate to those particular claims. A source match or barcode routing candidate cannot authorize complete
identity acceptance. Barcode fields remain untrusted claims and routing may return more
than one design. DAJ is a cardholder address jurisdiction, not an issuer identifier.

The current deliverable is public collection metadata and anonymous access to the
`GET /v1/specimens` catalog and indexed, visibly marked PNG reference derivatives.
Visitors need no KYB, DNS verification, application, or API key. Original archives and
raw sources remain in a protected vault; ingestion and administration remain authorized
operator operations. It makes no claim of a complete 51-state reviewed design catalog, native
SDK integration, physical-card acceptance, optical-feature qualification, or an automatic
fraud verdict. Those require independent implementation and validation checkpoints.
