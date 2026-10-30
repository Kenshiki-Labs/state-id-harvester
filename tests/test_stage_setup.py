"""Offline Stage readiness rejects mixed resources and generates only private key files."""

import hashlib
import importlib.util
import json
import shutil
import stat

import pytest

spec = importlib.util.spec_from_file_location("cadastre_stage_setup", "scripts/stage_setup.py")
assert spec and spec.loader
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.fixture
def checkout(tmp_path):
    (tmp_path / "web").mkdir()
    config = json.loads((setup.ROOT / "web/wrangler.jsonc").read_text())
    config["env"]["stage"]["d1_databases"][0]["database_id"] = (
        "00000000-0000-0000-0000-000000000000"
    )
    (tmp_path / "web/wrangler.jsonc").write_text(json.dumps(config))
    shutil.copytree(setup.ROOT / "web/migrations", tmp_path / "web/migrations")
    return tmp_path


def test_plan_is_deterministic_and_stage_only(checkout):
    plan = setup.plan(checkout)
    assert plan == setup.plan(checkout)
    assert plan["migrations"][0]["name"] == "0001_access.sql"
    assert not plan["live_readiness_proven"]
    assert plan["bucket"] == "cadastre-specimens-stage"
    for command in plan["commands_require_separate_execution"].values():
        assert command[-2:] == ["--env", "stage"]


def test_placeholder_cannot_claim_readiness(checkout):
    with pytest.raises(ValueError, match="not provisioned"):
        setup.check_evidence({}, checkout)


def test_recorded_readiness_requires_stage_bucket_and_complete_migrations(checkout):
    path = checkout / "web/wrangler.jsonc"
    config = json.loads(path.read_text())
    identifier = "11111111-1111-4111-8111-111111111111"
    config["env"]["stage"]["d1_databases"][0]["database_id"] = identifier
    path.write_text(json.dumps(config))
    evidence = {
        "schema": "kenshiki.stage-infrastructure-evidence.v1",
        "environment": "stage",
        "account_id": setup.ACCOUNT,
        "worker_name": setup.WORKER,
        "database": {"name": setup.DATABASE, "uuid": identifier},
        "bucket_names": [setup.BUCKET],
        "applied_migrations": [item["name"] for item in setup.migration_manifest(checkout)],
        "secret_names": sorted(setup.SECRET_NAMES),
    }
    setup.check_evidence(evidence, checkout)
    for field, value in (
        ("bucket_names", ["cadastre-specimens"]),
        ("applied_migrations", []),
        ("secret_names", []),
    ):
        with pytest.raises(ValueError):
            setup.check_evidence({**evidence, field: value}, checkout)


@pytest.mark.parametrize("field", ["bucket", "database", "origin", "rate_limit", "public"])
def test_mixed_or_public_targets_are_refused(checkout, field):
    path = checkout / "web/wrangler.jsonc"
    config = json.loads(path.read_text())
    stage = config["env"]["stage"]
    if field == "bucket":
        stage["r2_buckets"] = config["r2_buckets"]
    elif field == "database":
        stage["d1_databases"][0]["database_id"] = config["d1_databases"][0]["database_id"]
    elif field == "origin":
        stage["vars"]["PUBLIC_ORIGIN"] = config["vars"]["PUBLIC_ORIGIN"]
    elif field == "rate_limit":
        stage["ratelimits"] = config["ratelimits"]
    else:
        stage["workers_dev"] = True
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        setup.plan(checkout)


def test_private_fresh_keys_match_worker_hashes_and_cannot_be_overwritten(checkout):
    setup.generate_secrets(checkout)
    directory = checkout / ".stage-local"
    operator = json.loads((directory / "operator-secrets.json").read_text())
    worker = json.loads((directory / "worker-secrets.json").read_text())
    assert set(worker) == setup.SECRET_NAMES
    for name in ("CADASTRE_ADMIN_KEY", "CADASTRE_INGEST_KEY"):
        assert worker[name + "_HASH"] == hashlib.sha256(operator[name].encode()).hexdigest()
    assert len(set(worker.values())) == len(worker)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in directory.iterdir())
    with pytest.raises(FileExistsError):
        setup.generate_secrets(checkout)
