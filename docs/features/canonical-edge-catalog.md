# Public catalog through the canonical edge

## Feature

The shipping Cadastre browser obtains its specimen and ID-1 metadata, images, knowledge previews
and PNG downloads from `https://gateway.kenshikilabs.com/services/cadastre`. A single anonymous
transport owns JSON reads, cancellation, cookie omission and redirect refusal. Closed route
construction refuses administrative, ingestion, application and alternate-origin URLs. CSP allows
the canonical origin for these connections and images.

The backend retains its indexed-object, source-hash, checksum, reference-only and normalization
lineage checks. Only GET/HEAD public catalog responses receive CORS for
`https://cadastre.kenshikilabs.com`; no credentialed CORS is granted. `download=1` selects an
attachment response so the browser still downloads the original verified PNG when the API is
cross-origin. Ordinary image responses remain inline.

The public artifact contract now recognizes that exact canonical transport prefix for the same
previously allowed indexed specimen paths and fixed hash-bound browser variants. The prior
relative spelling remains valid during migration. Other hosts, services, private paths, active
attributes, arbitrary queries and embedded media remain rejected; existing adversarial cases are
retained alongside canonical-prefix counterexamples. The first complete run exposed the old
relative-only contract after the new 59-page build, prompting this explicit transport migration.

This is a bounded client port, not evidence that the gateway public-read classification is deployed
or that the old Cadastre custom domain has been detached. Static pages retain their existing
hostname. The retired application form/manager is absent from shipping pages (`/access` redirects
to `/catalog`); its retained libraries are not revived or refactored. Protected ingestion and
administrative automation must have a reviewed ingress before backend public access is removed.

## Test plan

- Run `npm run check`: the unchanged Python gate, all web checks/tests/coverage, Astro build,
  bundled publication scan and runtime dependency audit.
- Exercise the actual frontend URL builders, request dispatch and markup through the named
  `catalog-edge`, `specimens-frontend`, `viewer` and `knowledge` suites.
- Use the real Worker/R2 `browser-images` suite for identical PNG bytes, an attachment filename,
  ordinary inline delivery, CORS on success/refusal and preserved checksum/source/lineage checks.
- Qualify a real production browser only after paired gateway and Cadastre deployment: metadata,
  thumbnails, modal, zoom, download, retry and cancellation; inspect actual CSP and network URLs.

### Adversarial

- Reject alternate URLs, encoded separators, traversal, credential query strings and noncatalog
  operations before dispatch. A failed redirect is never retried at an old hostname.
- Arbitrary origins, null Origin, writes, preflight, admin, ingestion and application routes gain
  no CORS authority. Cache variation includes absent and foreign Origin.
- Anonymous public reference reads are distinct from client identity-processing operations;
  classifying the catalog must not exempt another backend or a protected native route.

## Changes

- Pending source checkpoint: canonical public catalog transport, CSP, narrow backend CORS and
  cross-origin download behavior. Existing data, supplier, approval and storage policies retained.

## Review

- Independent exact-source review pending. Source tests and deployment/device/browser acceptance
  are separate evidence levels; no production acceptance is asserted by this document.
