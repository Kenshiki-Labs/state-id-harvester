# Isolated Cadastre Stage profile

## Feature

Cadastre has an explicit private Stage API profile beside the production backend.
The profile selects its logical origin, issued-key prefix and image-cache name.
Wrangler declares separate D1, R2 and rate-limit resources. Unknown profiles,
mismatched configured origins and cross-profile requests fail before routing.
Existing administrative and ingestion bearer authorization remains in force.

This prepares a shared Stage backend; it does not establish that pulse-gov-demo
needs the catalog. It does not create a Stage website, publish reference data,
seed an access approval or prove deployment. The production static website keeps
its existing transport. See [operating boundaries](../stage-profile.md).

## Test plan

Run `npm run check` before integration. Its SDLC, Python and web checks remain
unchanged: lint, type checking, tests/coverage, schema comparison, publication
guards, builds and runtime dependency audit. CI validates pull requests and
pushes to `dev`/`main`; a feature-branch push alone starts no workflow.

Focused review commands are `.venv/bin/pytest -q tests/test_stage_setup.py` at the
repository root and `npm test -- --run tests/stage-deployment.test.ts` in `web`.
These exercise offline resource/key handling and the Worker profile boundary.
Full publication and browser-image regressions remain part of the complete gate.

### Adversarial

- Reject unknown/missing Stage selection with a Stage origin, production origin
  under Stage selection, arbitrary configured origins and cross-profile requests.
- Keep administrative requests unauthorized without the existing bearer secret.
  Public GET/HEAD catalog CORS is restricted to the selected browser origin and
  does not grant credentialed access.
- Refuse production bucket/database reuse, production rate-limit namespaces,
  public Stage exposure, incomplete migration ledgers and missing secret names.
- Refuse overwriting private key files. Verify independent admin/ingest keys,
  matching Worker hashes, distinct trace material and restrictive permissions.
- A missing specimen index remains `catalog_unavailable`; an empty bucket must
  not be reported as a working reference-data service.
- Exercise the offline CLI with valid stdin content, the byte-limit boundary,
  empty/malformed/non-object/deeply nested/oversized inputs, production-resource
  evidence and the rejected legacy filename option. Invalid content must not be
  echoed or produce a traceback.

## Changes

- Sonar cleanup: the offline checker now validates at most 64 KiB of supplied
  UTF-8 JSON on stdin instead of opening a caller-selected evidence filename.
  This preserves receipt custody outside the repository and existing Stage
  identity checks while removing filename authority and the optional-path
  dereference. The documented CLI invocation changes accordingly. Profile
  selection uses explicit branches with the same production defaults and
  unknown-profile refusal; the test import assertions are separate.
- `49cbcead0ca12c844dd6e43cd4b9cc8741568796`: added the deployment profile,
  Worker origin boundary, selected CORS/key/cache identities, isolated Wrangler
  environment and generated binding types, offline setup tooling and tests.
  No migration, reference-data, dependency or production website bytes changed.
- Review on 2026-11-02 read all 10 changed files in full and compared the runtime
  delta with `origin/dev`. The tree was clean at that code tip. Focused tests
  passed: **9 Python tests and 8 Worker tests**. `git diff --check origin/dev...HEAD`
  passed. These are local tests, not live resource or app acceptance.
- `npm run check:sdlc` failed on that committed tip because the code commit lacked
  a `docs/features/*.md` record. This document supplies the feature/review record
  without changing the gate. Its committed-range check remains blocked until an
  authorized commit includes this record. The required `npm run check` was also
  run and exited 1 at the same first SDLC step, before its Python and web gates.
  No gate was bypassed.

## Review

- `1e3d88947a75053ac5acb52a2c82757b8c6eff54`: independent review on
  2026-11-02 read all five cleanup files in full and verified their committed
  hashes against the approved checkpoint. The committed tree was clean; no
  material findings. Simplification/SOLID/DRY: bounded content parsing has one
  owner, `check_evidence` remains the resource validator, and explicit profile
  branches preserve the existing defaults without a second policy. Security:
  stdin has a 64 KiB limit, invalid JSON/encoding/recursion errors omit input,
  an object is required, and the old filename argument is rejected. Production
  defaults and origin refusal are unchanged. The identical precommit bytes
  passed 23 focused Python tests, 8 Worker tests and the full `npm run check`
  (696 Python and 319 web tests); the independent reviewer also ran the 23
  Python tests. Hosted Sonar reanalysis remains required after publication.
- `49cbcead0ca12c844dd6e43cd4b9cc8741568796` reviewed in full: `.gitignore`,
  `docs/stage-profile.md`, `scripts/stage_setup.py`, `tests/test_stage_setup.py`,
  `web/src/catalog-cors.ts`, `web/src/deployment.ts`, `web/src/worker.ts`,
  `web/tests/stage-deployment.test.ts`, `web/worker-configuration.d.ts` and
  `web/wrangler.jsonc`. No blocking runtime finding in this delta.
- Simplification/SOLID: the profile owns deployment identity, setup tooling owns
  offline resource checks, and existing Worker functions retain storage and
  authorization responsibilities. A separate Stage router would duplicate those
  responsibilities without improving this change.
- DRY: key issuance, CORS and image caching use the same selected profile. Repeated
  profile resolution in internal helpers is small and side-effect free; threading
  another parameter through every handler is not required. No unrelated refactor
  was included.
- Security: unknown/mixed profiles fail closed; admin/ingest hashes, trace key,
  request/audit tables and reference vault stay separate from production.
  Cloudflare's [environment contract](https://developers.cloudflare.com/workers/wrangler/environments/)
  requires environment-specific bindings and secrets; storage and rate limits are
  declared separately. Captured evidence checks names/identity, not live schema
  contents, applied migration hashes or published-reference acceptance.
- Remaining release limits: `web/package.json` exposes raw Wrangler deployment,
  not an immutable-source Stage release orchestrator. `scripts/vault_sync.py`
  defaults to the production origin and accepts only an HTTPS origin, not the
  Gateway service path. Publishing into the private Stage vault needs a reviewed
  Stage ingress/tooling path before use. No publication or deployment occurred.
