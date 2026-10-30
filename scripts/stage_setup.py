"""Offline Cadastre Stage inventory, captured-evidence checks and fresh local keys.

No command contacts Cloudflare, publishes reference data or deploys the Worker.
"""

import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "45c6882cb63b0ec680263ca4649fe848"
WORKER = "kenshiki-cadastre-stage"
DATABASE = "cadastre-access-stage"
BUCKET = "cadastre-specimens-stage"
SECRET_NAMES = {"CADASTRE_ADMIN_KEY_HASH", "CADASTRE_INGEST_KEY_HASH", "CADASTRE_TRACE_KEY"}


def configuration(root: Path = ROOT, *, ready: bool = False) -> dict:
    config = json.loads((root / "web/wrangler.jsonc").read_text())
    stage = config["env"]["stage"]
    expected = {
        "name": WORKER,
        "workers_dev": False,
        "preview_urls": False,
        "routes": [],
        "vars": {
            "CADASTRE_DEPLOYMENT_ENVIRONMENT": "stage",
            "PUBLIC_ORIGIN": "https://cadastre-stage.kenshikilabs.com",
        },
        "r2_buckets": [{"binding": "VAULT", "bucket_name": BUCKET}],
        "images": {"binding": "IMAGES"},
    }
    if config.get("account_id") != ACCOUNT or any(stage.get(k) != v for k, v in expected.items()):
        raise ValueError("Stage account, exposure, authority or storage mismatch")
    limits = [
        (entry["name"], entry["namespace_id"], entry["simple"]) for entry in stage["ratelimits"]
    ]
    if limits != [
        ("RATE_LIMITER", "2001", {"limit": 10, "period": 60}),
        ("INGEST_LIMITER", "2002", {"limit": 120, "period": 60}),
        ("PUBLIC_READ_LIMITER", "2003", {"limit": 300, "period": 60}),
    ]:
        raise ValueError("Stage rate-limit isolation mismatch")
    databases = stage["d1_databases"]
    if (
        len(databases) != 1
        or databases[0].get("binding") != "DB"
        or databases[0].get("database_name") != DATABASE
        or databases[0].get("migrations_dir") != "./migrations"
    ):
        raise ValueError("Stage D1 binding mismatch")
    identifier = UUID(databases[0]["database_id"])
    if str(identifier) != databases[0]["database_id"] or databases[0]["database_id"] in {
        db["database_id"] for db in config["d1_databases"]
    }:
        raise ValueError("Stage D1 identifier is invalid or aliases production")
    if ready and identifier.int == 0:
        raise ValueError("Stage D1 is not provisioned")
    return stage


def migration_manifest(root: Path = ROOT) -> list[dict[str, str]]:
    return [
        {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted((root / "web/migrations").glob("*.sql"))
    ]


def plan(root: Path = ROOT) -> dict:
    stage = configuration(root)
    prefix = ["npx", "--yes", "wrangler@4.152.0"]
    scope = ["--config", "web/wrangler.jsonc", "--env", "stage"]
    return {
        "schema": "kenshiki.stage-setup-plan.v1",
        "environment": "stage",
        "account_id": ACCOUNT,
        "worker_name": WORKER,
        "database": stage["d1_databases"][0],
        "bucket": BUCKET,
        "migrations": migration_manifest(root),
        "secret_names": sorted(SECRET_NAMES),
        "deployment_required_bindings": [
            "ASSETS",
            "IMAGES",
            "RATE_LIMITER",
            "INGEST_LIMITER",
            "PUBLIC_READ_LIMITER",
        ],
        "commands_require_separate_execution": {
            "create_database": prefix + ["d1", "create", DATABASE] + scope,
            "create_bucket": prefix + ["r2", "bucket", "create", BUCKET] + scope,
            "database_info": prefix + ["d1", "info", DATABASE, "--json"] + scope,
            "apply_migrations": prefix
            + ["d1", "migrations", "apply", DATABASE, "--remote"]
            + scope,
            "migration_ledger": prefix
            + [
                "d1",
                "execute",
                DATABASE,
                "--remote",
                "--json",
                "--command",
                "SELECT name FROM d1_migrations ORDER BY name",
            ]
            + scope,
        },
        "command_environment": {"CLOUDFLARE_ACCOUNT_ID": ACCOUNT},
        "live_readiness_proven": False,
    }


def check_evidence(evidence: dict, root: Path = ROOT) -> None:
    stage = configuration(root, ready=True)
    expected = {
        "schema": "kenshiki.stage-infrastructure-evidence.v1",
        "environment": "stage",
        "account_id": ACCOUNT,
        "worker_name": WORKER,
        "database": {"name": DATABASE, "uuid": stage["d1_databases"][0]["database_id"]},
        "bucket_names": [BUCKET],
        "applied_migrations": [item["name"] for item in migration_manifest(root)],
    }
    if set(evidence) != {*expected, "secret_names"} or any(
        evidence.get(k) != v for k, v in expected.items()
    ):
        raise ValueError("Captured Stage resource or migration evidence mismatch")
    names = evidence.get("secret_names")
    if (
        not isinstance(names, list)
        or not all(isinstance(name, str) for name in names)
        or not SECRET_NAMES.issubset(names)
    ):
        raise ValueError("Required Stage secret names are absent")


def write_private(path: Path, value: dict) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def generate_secrets(root: Path = ROOT) -> None:
    configuration(root)
    directory = root / ".stage-local"
    directory.mkdir(mode=0o700)
    admin = "cadastre-stage-admin." + secrets.token_urlsafe(48)
    ingest = "cadastre-stage-ingest." + secrets.token_urlsafe(48)
    write_private(
        directory / "operator-secrets.json",
        {
            "CADASTRE_ADMIN_KEY": admin,
            "CADASTRE_INGEST_KEY": ingest,
        },
    )
    write_private(
        directory / "worker-secrets.json",
        {
            "CADASTRE_ADMIN_KEY_HASH": hashlib.sha256(admin.encode()).hexdigest(),
            "CADASTRE_INGEST_KEY_HASH": hashlib.sha256(ingest.encode()).hexdigest(),
            "CADASTRE_TRACE_KEY": secrets.token_urlsafe(48),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "check", "secrets"))
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if args.command == "plan":
        print(json.dumps(plan(), indent=2, sort_keys=True))
    elif args.command == "secrets":
        generate_secrets()
        print("Fresh Stage operator keys and Worker hashes written under .stage-local.")
    else:
        if args.evidence is None:
            parser.error("check requires --evidence")
        check_evidence(json.loads(args.evidence.read_text()))
        print(
            "Stage configuration and captured infrastructure evidence agree; "
            "live service acceptance is unverified."
        )


if __name__ == "__main__":
    main()
