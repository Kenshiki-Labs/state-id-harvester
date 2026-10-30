# Cadastre Stage profile

`web/wrangler.jsonc` declares the private `stage` Worker. It has no public routes,
workers.dev URL, or preview URL. Gateway calls its Service Binding using the
logical origin `https://cadastre-stage.kenshikilabs.com`; no public DNS record is
needed for that identity. `CADASTRE_DEPLOYMENT_ENVIRONMENT=stage` and
`PUBLIC_ORIGIN` must match. Unknown profiles, mixed origin configuration, and
cross-profile request origins fail before routing or storage access.

The default profile remains production. Stage selects its own key prefix,
browser image cache, browser CORS origin, D1 database, R2 vault and rate-limit
namespaces. Existing administrative and ingestion bearer authorization remains
required. Stage public catalog reads retain the existing anonymous-read contract.

The Stage D1 UUID identifies its independently provisioned database. Before any
deployment, apply and verify the existing migrations, verify the Stage R2 vault,
and bind independently generated Stage
`CADASTRE_ADMIN_KEY_HASH`, `CADASTRE_INGEST_KEY_HASH`, and `CADASTRE_TRACE_KEY`.
Populate only reviewed, authorized reference data. Never reuse production
credentials or point a Stage binding at production storage.

This change covers the API backend. The static production website continues to
use its existing Gateway URL; it is not a separately deployed Stage website.
Resource provisioning and migration evidence are separate from this source
declaration. Local tests do not establish live binding or deployed acceptance.

## Offline setup and readiness

Run `.venv/bin/python scripts/stage_setup.py plan` from the repository root.
The deterministic JSON names the Stage D1 database and R2 bucket, current
migration hashes, required secret names, and explicit Wrangler command arrays.
The script executes none of those commands. Use the emitted account environment
and `--env stage` when independently authorized to create resources or apply the
unmodified Stage migration files. The Worker, Images binding, static assets and
rate-limit bindings are configured by a separate deployment, not by bucket creation.

`.venv/bin/python scripts/stage_setup.py secrets` creates a new `.stage-local/`
directory with mode 0700 and files with mode 0600. It refuses existing files and
prints no key values. `operator-secrets.json` contains distinct admin and ingestion
bearer keys; `worker-secrets.json` contains their SHA-256 hashes and an independent
trace HMAC key. Only the latter file belongs in Worker secrets. Neither file is
committable. Coordinate the generation once; never copy production credentials.

`scripts/stage_setup.py check --evidence <file>` validates recorded resource and
secret-name evidence against the current Stage config. The schema is
`kenshiki.stage-infrastructure-evidence.v1`, with `environment`, `account_id`,
`worker_name`, `database` (`name`, `uuid`), `bucket_names`, ordered
`applied_migrations`, and `secret_names`. Missing resources, production reuse,
unapplied migrations and missing secret names fail. Raw Cloudflare receipts must
be retained separately; this offline validation is not a deployed connectivity test.

No tenant row or access approval is seeded. Public catalog reads retain their
existing anonymous contract; administrative and ingestion routes require their
separate bearer authorities. Populate the Stage vault only from an independently
authorized, reviewed reference export. Do not copy production request/audit rows
or private archives as a setup shortcut.
