"""Release authorization and observation are separate from upload acceptance."""

import importlib
import io
import json
import os
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


@pytest.fixture
def custody(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setattr(release, "account_home", lambda: home)
    return home.joinpath(*release.EVIDENCE_PARTS)


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
    candidate = {**probe(), field: value}
    original = uploaded()
    timestamp = NOW.timestamp()
    with pytest.raises(ValueError):
        release.validate_probe(candidate, original, timestamp)


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
        stream = io.BytesIO(data)
        with pytest.raises(ValueError) as error:
            release.read_input(stream)
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
            assert host == "api.cloudflare.com"
            assert timeout == 30

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
def test_upload_orchestration_is_closed_and_never_calls_production(monkeypatch, custody, failure):
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
        bundle.add(release.ROOT / "web/migrations", arcname="web/migrations")
    calls = []
    schema_roots = []
    real_expected_schema = release.expected_schema

    def snapshot_schema(root=release.ROOT):
        schema_roots.append(root)
        return real_expected_schema(root)

    monkeypatch.setattr(release, "expected_schema", snapshot_schema)

    def gate(argv, **kwargs):
        assert argv == ["npm", "run", "check"]
        assert "CI" not in kwargs["env"]
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
        assert "apply" not in argv
        assert "production" not in argv
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
                rows = [] if failure == "schema" else real_expected_schema()
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
    output = Path("run")
    if failure:
        with pytest.raises(ValueError):
            release.upload(REVISION, evidence, output)
        assert not any("--secrets-file" in call for call in calls)
    else:
        receipt = release.upload(REVISION, evidence, output)
        assert receipt["state"] == "uploaded-pending-private-verification"
        assert len([call for call in calls if "--secrets-file" in call]) == 1
        assert len(schema_roots) == 1
        assert schema_roots[0] != release.ROOT


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


def test_custody_ignores_environment_home(monkeypatch):
    expected = Path(release.pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)
    monkeypatch.setenv("HOME", "/untrusted/home")
    assert release.account_home() == expected


def test_upload_directory_and_verify_file_share_private_custody(custody):
    directory = release.create_evidence_directory(Path("run"))
    assert directory == custody / "run"
    assert directory.stat().st_mode & 0o077 == 0
    release.write_json(directory / "verified.json", {"state": "private-build-verified"})
    receipt = directory / "verified.json"
    assert receipt.stat().st_mode & 0o077 == 0
    original = receipt.read_bytes()
    with pytest.raises(FileExistsError):
        release.write_json(receipt, {"replacement": True})
    assert receipt.read_bytes() == original
    with pytest.raises(FileExistsError):
        release.create_evidence_directory(directory)


@pytest.mark.parametrize("path", ["../escape", "run/../../escape", "/tmp/escape", "."])
def test_both_output_operations_reject_escape(custody, path):
    candidate = Path(path)
    with pytest.raises(ValueError):
        release.create_evidence_directory(candidate)
    with pytest.raises(ValueError):
        release.write_json(candidate, {})
    assert not custody.exists()


def test_sibling_prefix_and_source_custody_are_rejected(custody):
    sibling = custody.with_name(custody.name + "-untrusted") / "run"
    with pytest.raises(ValueError):
        release.create_evidence_directory(sibling)
    source = custody.parent
    output = Path("run")
    with pytest.raises(ValueError):
        release.create_evidence_directory(output, source)
    nested_source = custody / "run"
    with pytest.raises(ValueError):
        release.create_evidence_directory(output, nested_source)
    assert not custody.exists()


def test_symlink_components_and_final_targets_are_never_followed(custody, tmp_path):
    directory = release.create_evidence_directory(Path("run"))
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    link = custody / "linked"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        release.create_evidence_directory(link / "new")
    with pytest.raises(OSError):
        release.write_json(link / "receipt.json", {})
    final = directory / "receipt.json"
    victim = outside / "victim.json"
    victim.write_text("unchanged")
    final.symlink_to(victim)
    with pytest.raises(FileExistsError):
        release.write_json(final, {})
    assert victim.read_text() == "unchanged"
    assert sorted(p.name for p in outside.iterdir()) == ["victim.json"]


def test_insecure_or_foreign_custody_is_refused(custody, monkeypatch):
    directory = release.create_evidence_directory(Path("run"))
    directory.chmod(0o755)
    with pytest.raises(ValueError):
        release.write_json(directory / "receipt.json", {})
    directory.chmod(0o700)
    monkeypatch.setattr(release.os, "getuid", lambda: os.stat(directory).st_uid + 1)
    with pytest.raises(ValueError):
        release.write_json(directory / "receipt.json", {})


def test_protected_root_cannot_be_a_symlink(custody, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    home = custody.parents[2]
    (home / ".kenshiki").symlink_to(outside, target_is_directory=True)
    output = Path("run")
    with pytest.raises(OSError):
        release.create_evidence_directory(output)
    assert not list(outside.iterdir())


@pytest.mark.parametrize("output", ["run/verified.json", "../escape.json", "/tmp/escape.json"])
def test_verify_cli_uses_the_same_output_boundary(custody, monkeypatch, output):
    release.create_evidence_directory(Path("run"))
    uploaded_at = datetime.now(UTC).isoformat()
    evidence = {
        "upload": {**uploaded(), "uploadedAt": uploaded_at},
        "probe": {**probe(), "observedAt": uploaded_at},
    }
    stream = io.TextIOWrapper(io.BytesIO(json.dumps(evidence).encode()))
    monkeypatch.setattr(sys, "stdin", stream)
    monkeypatch.setattr(
        sys, "argv", ["stage_release.py", "verify", "--revision", REVISION, "--output", output]
    )
    if output == "run/verified.json":
        release.main()
        receipt = json.loads((custody / output).read_text())
        assert receipt["state"] == "private-build-verified"
    else:
        with pytest.raises(ValueError):
            release.main()
        assert not list((custody / "run").iterdir())


def test_parent_substitution_after_admission_cannot_redirect_write(custody, tmp_path, monkeypatch):
    directory = release.create_evidence_directory(Path("run"))
    moved = custody / "retained-run"
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    real_open = os.open

    def substitute(path, flags, *args, **kwargs):
        if path == "receipt.json":
            directory.rename(moved)
            directory.symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(release.os, "open", substitute)
    release.write_json(directory / "receipt.json", {"retained": True})
    assert not list(outside.iterdir())
    assert json.loads((moved / "receipt.json").read_text()) == {"retained": True}
