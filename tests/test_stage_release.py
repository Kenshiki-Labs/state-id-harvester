"""Release authorization and observation are separate from upload acceptance."""

import importlib
import io
import json
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    release = importlib.import_module("scripts.stage_release")
finally:
    sys.path.pop(0)

REVISION = "a" * 40
VERSION = "11111111-2222-4333-8444-555555555555"
NOW = datetime(2026, 11, 2, tzinfo=UTC)


def uploaded():
    return {
        **release.plan(REVISION),
        "state": "uploaded-pending-private-verification",
        "build": "b" * 32,
        "versionId": VERSION,
        "uploadedAt": NOW.isoformat(),
    }


def probe():
    upload = uploaded()
    return {
        **{
            key: upload[key]
            for key in (
                "accountId",
                "workerName",
                "sourceRevision",
                "configSha256",
                "versionId",
                "build",
            )
        },
        "schema": "kenshiki.stage-private-probe.v1",
        "transport": "remote-service-binding",
        "origin": release.ORIGIN,
        "routes": [],
        "workersDev": False,
        "previewUrls": False,
        "services": [],
        "status": 200,
        "observedAt": NOW.isoformat(),
    }


def test_probe_accepts_only_matching_remote_stage_observation():
    release.validate_probe(probe(), uploaded(), NOW.timestamp())


@pytest.mark.parametrize(
    "field,value",
    [
        ("accountId", "0" * 32),
        ("workerName", "kenshiki-cadastre"),
        ("sourceRevision", "c" * 40),
        ("configSha256", "c" * 64),
        ("versionId", "bad"),
        ("build", "dev"),
        ("transport", "local-service-binding"),
        ("origin", "https://cadastre.kenshikilabs.com"),
        ("routes", ["public.example"]),
        ("workersDev", True),
        ("previewUrls", True),
        ("status", 503),
        ("services", [{}]),
        ("observedAt", "2026-11-01T00:00:00+00:00"),
    ],
)
def test_probe_refuses_wrong_target_build_and_simulation(field, value):
    with pytest.raises(ValueError):
        release.validate_probe({**probe(), field: value}, uploaded(), NOW.timestamp())


def test_private_stdin_bounded_regular_file_and_error_omits_contents(tmp_path):
    path = tmp_path / "input.json"
    path.write_text('{"secret": "synthetic-only"}')
    path.chmod(0o600)
    with path.open("rb") as stream:
        assert release.read_input(stream, private=True) == {"secret": "synthetic-only"}
    path.chmod(0o644)
    with path.open("rb") as stream, pytest.raises(ValueError, match="private"):
        release.read_input(stream, private=True)
    for data in (b"", b"x" * (1024 * 1024 + 1), b"synthetic-sensitive", b"[]"):
        with pytest.raises(ValueError) as error:
            release.read_input(io.BytesIO(data))
        assert "synthetic-sensitive" not in str(error.value)


def test_secret_names_hashes_and_separation():
    valid = {
        "CADASTRE_ADMIN_KEY_HASH": "a" * 64,
        "CADASTRE_INGEST_KEY_HASH": "b" * 64,
        "CADASTRE_TRACE_KEY": "c" * 48,
    }
    release.validate_secrets(valid)
    for change in (
        {"EXTRA": "d" * 64},
        {"CADASTRE_ADMIN_KEY_HASH": "not-a-digest"},
        {"CADASTRE_TRACE_KEY": "a" * 64},
    ):
        with pytest.raises(ValueError):
            release.validate_secrets({**valid, **change})


def test_schema_is_derived_from_migrations_and_refuses_missing_table():
    expected = release.expected_schema()
    release.validate_schema([{"success": True, "results": expected}], expected)
    assert {item["name"] for item in expected} >= {"access_requests", "api_keys", "audit_events"}
    with pytest.raises(ValueError):
        release.validate_schema([{"success": True, "results": expected[:-1]}], expected)


@pytest.mark.parametrize(
    "status,body",
    [
        (404, {}),
        (403, {}),
        (200, {"success": False, "errors": [], "result": []}),
        (200, {"success": True, "errors": [], "result": [{"id": release.setup.WORKER}]}),
        (200, {"success": True, "errors": [], "result": [], "result_info": {"total_count": 1}}),
        (200, {"success": True, "errors": [], "result": [], "result_info": {"cursor": "more"}}),
        (200, {"success": True, "errors": [], "result": [{"id": "other"}, {"id": "other"}]}),
    ],
)
def test_absence_requires_successful_complete_inventory(monkeypatch, status, body):
    class Response:
        def read(self, _limit):
            return json.dumps(body).encode()

    response = Response()
    response.status = status

    class Connection:
        def __init__(self, host, timeout):
            assert host == "api.cloudflare.com" and timeout == 30

        def request(self, method, path, headers):
            assert method == "GET"
            assert path == f"/client/v4/accounts/{release.setup.ACCOUNT}/workers/scripts"
            assert headers == {"Authorization": "Bearer synthetic"}

        def getresponse(self):
            return response

        def close(self):
            pass

    monkeypatch.setattr(release.http.client, "HTTPSConnection", Connection)
    with pytest.raises(ValueError):
        release.require_absent_worker("synthetic")


@pytest.mark.parametrize("failure", [None, "gate", "ledger", "schema", "bucket", "exists"])
def test_upload_orchestration_is_closed_and_never_calls_production(monkeypatch, tmp_path, failure):
    planned = release.plan(REVISION)
    evidence = {
        "preflight": {
            **planned,
            "schema": "kenshiki.cadastre-stage-preflight.v1",
            "kind": "absent",
            "versionId": None,
            "observedAt": datetime.now(UTC).isoformat(),
        },
        "secrets": {
            "CADASTRE_ADMIN_KEY_HASH": "a" * 64,
            "CADASTRE_INGEST_KEY_HASH": "b" * 64,
            "CADASTRE_TRACE_KEY": "c" * 48,
        },
    }
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "synthetic-only")
    monkeypatch.setattr(
        release,
        "source_state",
        lambda _: {"head": REVISION, "branch": "main", "remoteMain": REVISION, "clean": True},
    )
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as bundle:
        bundle.add(release.ROOT / "web/src/stage-build.ts", arcname="web/src/stage-build.ts")
    calls = []

    def gate(argv, **kwargs):
        assert argv == ["npm", "run", "check"] and "CI" not in kwargs["env"]
        assert "CLOUDFLARE_API_TOKEN" not in kwargs["env"]
        return subprocess.CompletedProcess(argv, 1 if failure == "gate" else 0)

    monkeypatch.setattr(release.subprocess, "run", gate)

    def absent(_token):
        if failure == "exists":
            raise ValueError("already exists")
        return {"absent": True}

    monkeypatch.setattr(release, "require_absent_worker", absent)

    def mocked(argv, *args, **kwargs):
        calls.append(argv)
        if argv[:2] == ["git", "archive"]:
            return archive.getvalue()
        if argv[0] == "npm":
            assert "CLOUDFLARE_API_TOKEN" not in kwargs["env"]
            return b""
        assert argv[-2:] == ["--env", "stage"]
        assert "apply" not in argv and "production" not in argv
        if argv[1] == "deploy":
            return f"Current Version ID: {VERSION}\n".encode()
        if argv[1:3] == ["d1", "info"]:
            value = {"name": release.setup.DATABASE, "uuid": release.DATABASE_ID}
        elif argv[1:3] == ["d1", "execute"]:
            if "SELECT name FROM d1_migrations ORDER BY name" in argv:
                rows = (
                    []
                    if failure == "ledger"
                    else [{"name": item["name"]} for item in planned["migrations"]]
                )
            else:
                rows = [] if failure == "schema" else release.expected_schema()
            value = [{"success": True, "results": rows}]
        elif argv[1:3] == ["r2", "bucket"]:
            value = {"name": "production" if failure == "bucket" else release.setup.BUCKET}
        else:
            value = [
                {
                    "created_on": NOW.isoformat(),
                    "versions": [{"version_id": VERSION, "percentage": 100}],
                }
            ]
        return json.dumps(value).encode()

    monkeypatch.setattr(release, "command", mocked)
    if failure:
        with pytest.raises(ValueError):
            release.upload(REVISION, evidence, tmp_path / "output")
        assert not any("--secrets-file" in call for call in calls)
    else:
        receipt = release.upload(REVISION, evidence, tmp_path / "output")
        assert receipt["state"] == "uploaded-pending-private-verification"
        assert len([call for call in calls if "--secrets-file" in call]) == 1


def test_gate_environment_omits_ambient_credentials():
    result = release.release_environment(
        {
            "PATH": "/bin",
            "HOME": "/home/test",
            "CI": "1",
            "CLOUDFLARE_API_TOKEN": "synthetic",
            "TWILIO_AUTH_TOKEN": "synthetic",
            "NODE_OPTIONS": "unsafe",
        }
    )
    assert set(result) == {
        "PATH",
        "HOME",
        "CLOUDFLARE_ACCOUNT_ID",
        "WRANGLER_SEND_METRICS",
        "WRANGLER_LOAD_DOT_ENV",
    }


def test_extra_application_schema_is_rejected():
    expected = release.expected_schema()
    actual = expected + [{"name": "extra", "type": "table", "sql": "CREATE TABLE extra(id)"}]
    with pytest.raises(ValueError):
        release.validate_schema([{"success": True, "results": actual}], expected)


@pytest.mark.parametrize(
    "value",
    [
        b"",
        b"Current Version ID: invalid\n",
        ("Current Version ID: " + VERSION + "extra\n").encode(),
        ("Current Version ID: " + VERSION + "\n").encode() * 2,
    ],
)
def test_uploaded_version_is_one_exact_uuid(value):
    with pytest.raises(ValueError):
        release.uploaded_version(value)


def test_git_provenance_commands_do_not_inherit_repository_overrides(monkeypatch):
    monkeypatch.setenv("GIT_DIR", "/other/.git")
    monkeypatch.setenv("GIT_WORK_TREE", "/other")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "synthetic")
    calls = []

    def run(argv, **kwargs):
        assert "GIT_DIR" not in kwargs["env"]
        assert "GIT_WORK_TREE" not in kwargs["env"]
        assert "CLOUDFLARE_API_TOKEN" not in kwargs["env"]
        calls.append(argv)
        if argv[1] == "ls-remote":
            value = REVISION + "\trefs/heads/main"
        elif argv[1] == "rev-parse":
            value = REVISION
        elif argv[1] == "branch":
            value = "main"
        else:
            value = ""
        return subprocess.CompletedProcess(argv, 0, value.encode())

    monkeypatch.setattr(release.subprocess, "run", run)
    release.validate_source(release.source_state(), REVISION)
    release.command(["git", "archive", REVISION])
    assert len(calls) == 5
