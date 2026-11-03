"""Guarded private Stage release, separate from the existing production command.

upload reads {preflight, secrets} from a private regular file on stdin.
verify reads {upload, probe} on stdin. Neither command treats an upload as live proof.
"""

import argparse
import hashlib
import http.client
import io
import json
import os
import pwd
import re
import secrets
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from scripts import stage_setup as setup

ROOT = setup.ROOT
WRANGLER_CONFIG = "web/wrangler.jsonc"
EVIDENCE_PARTS = (".kenshiki", "stage-releases", "cadastre")
DATABASE_ID = "3a0417b4-d8e8-4325-84a9-4387eda0a6b3"
ORIGIN = "https://cadastre-stage.kenshikilabs.com"
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def account_home():
    # OS account custody, never a caller-controlled HOME or output-root override.
    return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)


@contextmanager
def private_directory(path, *, parent=None, create=False, home=False):
    if create:
        try:
            os.mkdir(path, mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass  # Existing custody is admitted below, never chmodded or replaced.
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        metadata = os.fstat(descriptor)
        forbidden = 0o022 if home else 0o077
        require(
            stat.S_ISDIR(metadata.st_mode)
            and metadata.st_uid == os.getuid()
            and metadata.st_mode & forbidden == 0,
            "Evidence directories must belong to this account and be private",
        )
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def evidence_parent(output, source_root=ROOT):
    home = account_home()
    base = home.joinpath(*EVIDENCE_PARTS)
    output = Path(output)
    candidate = output if output.is_absolute() else base / output
    require(candidate.is_relative_to(base) and candidate != base, "Output is outside Stage custody")
    relative = candidate.relative_to(base)
    require(".." not in relative.parts, "Output traversal is forbidden")
    require(
        source_root.resolve() not in (base, candidate)
        and source_root.resolve() not in base.parents
        and source_root.resolve() not in candidate.parents,
        "Evidence custody must be outside source checkout",
    )
    # Walk from a trusted home descriptor. Every component is opened without
    # following links; writes remain relative to the admitted parent descriptor.
    with ExitStack() as stack:
        descriptor = stack.enter_context(private_directory(home, home=True))
        for part in EVIDENCE_PARTS:
            descriptor = stack.enter_context(
                private_directory(part, parent=descriptor, create=True)
            )
        for part in relative.parts[:-1]:
            descriptor = stack.enter_context(private_directory(part, parent=descriptor))
        yield descriptor, relative.name, candidate


def create_evidence_directory(output, source_root=ROOT):
    with evidence_parent(output, source_root) as (parent, name, candidate):
        os.mkdir(name, mode=0o700, dir_fd=parent)
        return candidate


@contextmanager
def evidence_file(path):
    with evidence_parent(path) as (parent, name, _candidate):
        descriptor = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
        )
        with os.fdopen(descriptor, "wb") as stream:
            yield stream


def write_bytes(path, data):
    with evidence_file(path) as stream:
        stream.write(data)


def write_json(path, value):
    write_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def release_environment(environment, provider=False):
    result = {
        key: environment[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in environment
    }
    result.update(
        CLOUDFLARE_ACCOUNT_ID=setup.ACCOUNT,
        WRANGLER_SEND_METRICS="false",
        WRANGLER_LOAD_DOT_ENV="false",
    )
    if provider:
        require(
            bool(environment.get("CLOUDFLARE_API_TOKEN")), "Explicit deployment API token required"
        )
        result["CLOUDFLARE_API_TOKEN"] = environment["CLOUDFLARE_API_TOKEN"]
    return result


def read_input(stream, *, private=False):
    if private:
        metadata = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(metadata.st_mode) and metadata.st_mode & 0o077 == 0,
            "Upload input must be a private regular file",
        )
    data = stream.read(1024 * 1024 + 1)
    require(0 < len(data) <= 1024 * 1024, "Input size is invalid")
    try:
        value = json.loads(data)
    except (ValueError, RecursionError):
        raise ValueError("Input must be JSON; contents omitted") from None
    require(isinstance(value, dict), "Input must be an object")
    return value


def configuration(root=ROOT):
    stage = setup.configuration(root, ready=True)
    raw = json.loads((root / WRANGLER_CONFIG).read_text())
    require(
        set(raw)
        == {
            "$schema",
            "name",
            "account_id",
            "main",
            "compatibility_date",
            "compatibility_flags",
            "workers_dev",
            "preview_urls",
            "logpush",
            "observability",
            "routes",
            "assets",
            "vars",
            "images",
            "d1_databases",
            "r2_buckets",
            "ratelimits",
            "env",
        },
        "Unreviewed inherited capability",
    )
    require(raw["main"] == "src/worker.ts", "Unexpected entrypoint")
    require(
        raw["assets"]
        == {
            "directory": "./dist",
            "binding": "ASSETS",
            "run_worker_first": True,
            "html_handling": "drop-trailing-slash",
            "not_found_handling": "none",
        },
        "Unreviewed asset configuration",
    )
    require(
        set(stage)
        == {
            "name",
            "workers_dev",
            "preview_urls",
            "routes",
            "vars",
            "d1_databases",
            "r2_buckets",
            "images",
            "ratelimits",
        },
        "Unreviewed Stage capability",
    )
    require(
        stage["d1_databases"]
        == [
            {
                "binding": "DB",
                "database_name": setup.DATABASE,
                "database_id": DATABASE_ID,
                "migrations_dir": "./migrations",
            }
        ],
        "Stage database mismatch",
    )
    return stage


def plan(revision, root=ROOT):
    require(
        isinstance(revision, str) and re.fullmatch(r"[a-f0-9]{40}", revision),
        "Full reviewed source SHA required",
    )
    configuration(root)
    migrations = setup.migration_manifest(root)
    return {
        "schema": "kenshiki.cadastre-stage-release.v1",
        "accountId": setup.ACCOUNT,
        "workerName": setup.WORKER,
        "sourceRevision": revision,
        "configSha256": digest((root / WRANGLER_CONFIG).read_bytes()),
        "migrationsSha256": digest(json.dumps(migrations, sort_keys=True).encode()),
        "migrations": migrations,
        "services": [],
        "origin": ORIGIN,
    }


def validate_source(source, revision):
    require(
        source == {"head": revision, "branch": "main", "remoteMain": revision, "clean": True},
        "Require clean main at exact published reviewed SHA",
    )


def fresh(value, now):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "Observation requires timezone")
    observed = parsed.timestamp()
    require(0 <= now - observed <= 300, "Observation is stale or future dated")
    return observed


def validate_preflight(receipt, release, now):
    for key in ("accountId", "workerName", "sourceRevision", "configSha256", "migrationsSha256"):
        require(receipt.get(key) == release[key], "Preflight identity mismatch: " + key)
    require(
        receipt.get("schema") == "kenshiki.cadastre-stage-preflight.v1"
        and receipt.get("kind") == "absent"
        and receipt.get("versionId") is None,
        "This first-deploy executor requires an absent Stage Worker",
    )
    fresh(receipt["observedAt"], now)


def validate_secrets(value):
    require(
        isinstance(value, dict) and set(value) == setup.SECRET_NAMES,
        "Stage secret names differ from required isolated set",
    )
    require(
        all(isinstance(item, str) and len(item.strip()) >= 32 for item in value.values()),
        "Stage secret values must be nonempty",
    )
    for name in ("CADASTRE_ADMIN_KEY_HASH", "CADASTRE_INGEST_KEY_HASH"):
        require(re.fullmatch(r"[a-f0-9]{64}", value[name]), "Invalid Stage authorization digest")
    require(len(set(value.values())) == len(value), "Stage secrets must be distinct")


def validate_probe(receipt, uploaded, now):
    require(
        uploaded.get("state") == "uploaded-pending-private-verification", "Invalid upload state"
    )
    require(
        UUID.fullmatch(uploaded.get("versionId", ""))
        and re.fullmatch(r"[a-f0-9]{32}", uploaded.get("build", "")),
        "Invalid provenance",
    )
    expected = {
        key: uploaded[key]
        for key in (
            "accountId",
            "workerName",
            "sourceRevision",
            "configSha256",
            "versionId",
            "build",
        )
    }
    expected.update(
        schema="kenshiki.stage-private-probe.v1",
        transport="remote-service-binding",
        origin=ORIGIN,
        routes=[],
        workersDev=False,
        previewUrls=False,
        status=200,
        services=[],
    )
    require(
        all(receipt.get(key) == value for key, value in expected.items()),
        "Private live probe does not match uploaded Stage build",
    )
    require(
        receipt.get("workersDev") is False and receipt.get("previewUrls") is False,
        "Private exposure required",
    )
    require(
        fresh(receipt["observedAt"], now)
        >= datetime.fromisoformat(uploaded["uploadedAt"]).timestamp(),
        "Probe predates upload",
    )


def uploaded_version(data):
    lines = [line for line in data.decode().splitlines() if line.startswith("Current Version ID:")]
    require(len(lines) == 1, "Upload has no unique version receipt")
    version = lines[0].removeprefix("Current Version ID:").strip()
    require(UUID.fullmatch(version) is not None, "Upload version is malformed")
    return version


def command(argv, root=ROOT, *, env=None):
    if env is None:
        env = release_environment(os.environ)
    result = subprocess.run(argv, cwd=root, env=env, capture_output=True, check=False)
    require(result.returncode == 0, "Command failed: " + argv[0])
    return result.stdout


def source_state(root=ROOT):
    def git(*args):
        return command(["git", *args], root).decode().strip()

    remote = git("ls-remote", "--exit-code", "origin", "refs/heads/main").split()
    require(len(remote) == 2 and remote[1] == "refs/heads/main", "Cannot verify published main")
    return {
        "head": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "remoteMain": remote[0],
        "clean": git("status", "--porcelain") == "",
    }


def require_absent_worker(token):
    """One fixed API read; no redirect following, user-selected host or incomplete list."""
    connection = http.client.HTTPSConnection("api.cloudflare.com", timeout=30)
    try:
        connection.request(
            "GET",
            f"/client/v4/accounts/{setup.ACCOUNT}/workers/scripts",
            headers={"Authorization": "Bearer " + token},
        )
        response = connection.getresponse()
        require(response.status == 200, "Worker inventory request failed")
        data = response.read(4 * 1024 * 1024 + 1)
        require(len(data) <= 4 * 1024 * 1024, "Worker inventory exceeds bound")
        inventory = json.loads(data)
    finally:
        connection.close()
    require(
        inventory.get("success") is True
        and inventory.get("errors") == []
        and isinstance(inventory.get("result"), list),
        "Worker inventory failed",
    )
    scripts = inventory["result"]
    require(
        all(isinstance(item, dict) and isinstance(item.get("id"), str) for item in scripts),
        "Malformed Worker inventory",
    )
    info = inventory.get("result_info", {})
    require(
        info.get("total_count", len(scripts)) == len(scripts) and info.get("total_pages", 1) <= 1,
        "Incomplete Worker inventory",
    )
    require(
        not info.get("cursor") and len({item["id"] for item in scripts}) == len(scripts),
        "Partial or duplicate Worker inventory",
    )
    require(all(item["id"] != setup.WORKER for item in scripts), "Stage Worker already exists")
    return {"workerName": setup.WORKER, "absent": True, "observedAt": datetime.now(UTC).isoformat()}


def expected_schema(root=ROOT):
    with sqlite3.connect(":memory:") as database:
        for path in sorted((root / "web/migrations").glob("*.sql")):
            database.executescript(path.read_text())
        return [
            {"name": name, "type": kind, "sql": sql}
            for name, kind, sql in database.execute(
                "SELECT name,type,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]


def validate_schema(result, expected):
    require(
        isinstance(result, list) and len(result) == 1 and result[0].get("success") is True,
        "Remote schema query failed",
    )

    def normalized(items):
        return [{**item, "sql": " ".join(item["sql"].split())} for item in items]

    require(normalized(result[0]["results"]) == normalized(expected), "Remote Stage schema drift")


def upload(revision, evidence, output, root=ROOT):
    release = plan(revision, root)
    validate_source(source_state(root), revision)
    validate_preflight(evidence["preflight"], release, datetime.now(UTC).timestamp())
    validate_secrets(evidence["secrets"])
    require(
        os.environ.get("CLOUDFLARE_ACCOUNT_ID", setup.ACCOUNT) == setup.ACCOUNT,
        "Ambient account conflicts with Stage",
    )
    require(bool(os.environ.get("CLOUDFLARE_API_TOKEN")), "Explicit deployment API token required")
    output = create_evidence_directory(output, root)
    env = release_environment(os.environ, provider=True)
    with evidence_file(output / "check.log") as log:
        result = subprocess.run(
            ["npm", "run", "check"],
            cwd=root,
            env=release_environment(os.environ),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    write_json(output / "check.json", {"exitCode": result.returncode, "sourceRevision": revision})
    require(result.returncode == 0, "Full repository gate failed")
    validate_source(source_state(root), revision)
    require(plan(revision, root) == release, "Source changed during full gate")
    build = secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix="cadastre-stage-") as directory:
        snapshot = Path(directory)
        archive = command(["git", "archive", "--format=tar", revision], root)
        write_bytes(output / "source.tar", archive)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(snapshot, filter="data")
        stamp = snapshot / "web/src/stage-build.ts"
        original = stamp.read_text()
        require(original.count('export const STAGE_BUILD = "dev";') == 1, "Unexpected stamp source")
        stamp.write_text(
            original.replace(
                'export const STAGE_BUILD = "dev";', f'export const STAGE_BUILD = "{build}";'
            )
        )
        write_bytes(output / "stamped-stage-build.ts", stamp.read_bytes())
        build_env = release_environment(os.environ)
        command(["npm", "ci", "--prefix", "web", "--ignore-scripts"], snapshot, env=build_env)
        command(["npm", "run", "build", "--prefix", "web"], snapshot, env=build_env)
        cli = [str(snapshot / "web/node_modules/.bin/wrangler")]
        scope = ["--config", str(snapshot / WRANGLER_CONFIG), "--env", "stage"]
        count = 0

        def wrangler(*args):
            nonlocal count
            data = json.loads(command(cli + list(args) + scope, snapshot, env=env))
            count += 1
            retained = data
            if args[:2] == ("deployments", "list"):
                retained = [
                    {"created_on": item["created_on"], "versions": item["versions"]}
                    for item in data
                ]
            write_json(output / f"remote-{count}.json", retained)
            return data

        write_bytes(
            output / "dry-run.log",
            command(cli + ["deploy", "--strict", "--dry-run"] + scope, snapshot, env=build_env),
        )
        info = wrangler("d1", "info", setup.DATABASE, "--json")
        require(
            info.get("uuid") == DATABASE_ID and info.get("name") == setup.DATABASE,
            "Wrong remote Stage database",
        )
        ledger = wrangler(
            "d1",
            "execute",
            setup.DATABASE,
            "--remote",
            "--json",
            "--command",
            "SELECT name FROM d1_migrations ORDER BY name",
        )
        require(
            isinstance(ledger, list)
            and len(ledger) == 1
            and ledger[0].get("success") is True
            and ledger[0].get("results")
            == [{"name": item["name"]} for item in release["migrations"]],
            "Pending or extra migrations; Stage release never applies SQL",
        )
        expected = expected_schema(snapshot)
        schema = wrangler(
            "d1",
            "execute",
            setup.DATABASE,
            "--remote",
            "--json",
            "--command",
            "SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
            "AND name NOT IN ('d1_migrations','_cf_KV') ORDER BY name",
        )
        validate_schema(schema, expected)
        bucket = wrangler("r2", "bucket", "info", setup.BUCKET, "--json")
        require(
            isinstance(bucket, dict) and bucket.get("name") == setup.BUCKET,
            "Stage bucket absent",
        )
        # A failed lookup is not proof of absence. Require a complete successful inventory.
        absence = require_absent_worker(env["CLOUDFLARE_API_TOKEN"])
        write_json(output / "absence.json", absence)
        validate_source(source_state(root), revision)
        secret_file = snapshot / "stage-secrets.json"
        with os.fdopen(
            os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as stream:
            json.dump(evidence["secrets"], stream)
        started = datetime.now(UTC).isoformat()
        write_json(
            output / "attempt.json",
            {**release, "state": "upload-not-confirmed", "build": build, "startedAt": started},
        )
        data = command(
            cli + ["deploy", "--strict", "--secrets-file", str(secret_file)] + scope,
            snapshot,
            env=env,
        )
        write_bytes(output / "upload.log", data)
        version = uploaded_version(data)
        deployments = wrangler("deployments", "list", "--json")
        require(isinstance(deployments, list) and bool(deployments), "Missing deployment inventory")
        latest = max(deployments, key=lambda item: item["created_on"])
        require(
            latest.get("versions") == [{"version_id": version, "percentage": 100}],
            "Uploaded version is not solely active",
        )
    receipt = {
        **release,
        "state": "uploaded-pending-private-verification",
        "versionId": version,
        "build": build,
        "uploadedAt": started,
    }
    write_json(output / "upload.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "upload", "verify"))
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "plan":
        print(json.dumps(plan(args.revision), indent=2))
        return
    require(args.output is not None, "Output path required")
    evidence = read_input(sys.stdin.buffer, private=args.action == "upload")
    if args.action == "upload":
        upload(args.revision, evidence, args.output)
        print("Uploaded Stage candidate; pending independent private live verification")
    else:
        uploaded = evidence["upload"]
        require(
            all(uploaded.get(key) == value for key, value in plan(args.revision).items()),
            "Upload receipt differs from accepted release inputs",
        )
        validate_probe(evidence["probe"], uploaded, datetime.now(UTC).timestamp())
        write_json(args.output, {**uploaded, "state": "private-build-verified"})
        print(
            "Captured private build matches; reference publication and enrollment are unqualified"
        )


if __name__ == "__main__":
    main()
