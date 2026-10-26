"""Adversarial tests for merge-only reference-index publication; no network access."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

_spec = importlib.util.spec_from_file_location("vault_publication", "scripts/vault_sync.py")
assert _spec is not None
assert _spec.loader is not None
vault_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vault_sync)
POINTER = "indexes/specimens.json"


class FakeVault:
    def __init__(self, existing: bytes | None = None, *, fail_upload: int | None = None):
        self.objects = {} if existing is None else {POINTER: existing}
        self.writes: list[str] = []
        self.fail_upload = fail_upload
        self.uploads = 0

    def get(self, key, *, limit, missing_ok):
        assert key == POINTER
        assert limit == vault_sync.INDEX_LIMIT
        assert missing_ok
        return self.objects.get(key)

    def put(self, key, data, **kwargs):
        if key != POINTER:
            self.uploads += 1
            if self.uploads == self.fail_upload:
                raise RuntimeError("Simulated upload failure")
            assert kwargs["specimen"] is True
            assert len(kwargs["source_sha256"]) == 64
        self.writes.append(key)
        self.objects[key] = data


def png(level: int = 0) -> bytes:
    ok, data = cv2.imencode(".png", np.full((2, 3, 3), level, np.uint8))
    assert ok
    return data.tobytes()


def entry(state="ME", identity="sample", *, data: bytes | None = None, keyed=True):
    checksum = hashlib.sha256(png() if data is None else data).hexdigest()
    result = dict(
        id=identity,
        state=state,
        source_sha256="a" * 64,
        asset_sha256=checksum,
        review_status="reference_only",
    )
    if keyed:
        result["key"] = f"specimens/retained/{checksum}.png"
    return result


def encoded(items) -> bytes:
    return json.dumps({"specimens": items}).encode()


def batch(tmp_path: Path, items, assets: list[bytes] | None = None):
    (tmp_path / "specimens.json").write_bytes(encoded(items))
    for data in assets or []:
        (tmp_path / (hashlib.sha256(data).hexdigest() + ".png")).write_bytes(data)


def test_missing_index_publishes_valid_new_state(tmp_path):
    row = entry(keyed=False)
    batch(tmp_path, [row], [png()])
    vault = FakeVault()
    vault_sync.push_specimens(vault, tmp_path)
    result = json.loads(vault.objects[POINTER])["specimens"]
    assert result[0]["state"] == "ME"
    assert result[0]["key"] in vault.objects
    assert vault.writes[-1] == POINTER


def test_valid_new_states_merge_retains_existing_object_keys(tmp_path):
    original = entry()
    batch(tmp_path, [entry("MI", data=png(42), keyed=False)], [png(42)])
    vault = FakeVault(encoded([original]))
    vault_sync.push_specimens(vault, tmp_path)
    result = json.loads(vault.objects[POINTER])["specimens"]
    assert result[0] == original
    assert {x["state"] for x in result} == {"ME", "MI"}
    assert original["key"] not in vault.writes


@pytest.mark.parametrize(
    "bad",
    [
        b"",
        b"not json",
        b"null",
        b"[]",
        b'{"specimens":null}',
        encoded([entry("ZZ")]),
        encoded([{**entry(), "id": "../raw"}]),
        encoded([{**entry(), "source_sha256": 4}]),
        encoded([{**entry(), "review_status": "accepted"}]),
        encoded([{**entry(), "key": "snapshots/private.png"}]),
        encoded([{**entry(), "key": "specimens/../" + "b" * 64 + ".png"}]),
        encoded([{**entry(), "key": "specimens/retained/" + "b" * 64 + ".png"}]),
        encoded([{**entry(), "key": None}]),
        encoded([entry(), {**entry(), "source_sha256": "b" * 64}]),
    ],
)
def test_malformed_existing_index_is_never_treated_as_empty(tmp_path, bad):
    batch(tmp_path, [])
    vault = FakeVault(bad)
    with pytest.raises((ValueError, TypeError)):
        vault_sync.push_specimens(vault, tmp_path)
    assert vault.objects[POINTER] == bad
    assert vault.writes == []


def test_failed_new_upload_retains_old_pointer(tmp_path):
    old = encoded([entry()])
    batch(
        tmp_path,
        [entry("MD", data=png(1), keyed=False), entry("MI", data=png(2), keyed=False)],
        [png(1), png(2)],
    )
    vault = FakeVault(old, fail_upload=2)
    with pytest.raises(RuntimeError, match="upload failure"):
        vault_sync.push_specimens(vault, tmp_path)
    assert vault.objects[POINTER] == old
    assert POINTER not in vault.writes


def test_conflicting_existing_identity_rejected_before_upload(tmp_path):
    old = encoded([entry()])
    batch(tmp_path, [{**entry(keyed=False), "source_sha256": "b" * 64}], [png()])
    vault = FakeVault(old)
    with pytest.raises(ValueError, match="Conflicting"):
        vault_sync.push_specimens(vault, tmp_path)
    assert vault.writes == []


def test_conflicting_duplicate_in_new_batch_rejected(tmp_path):
    batch(tmp_path, [entry(keyed=False), {**entry(keyed=False), "asset_sha256": "b" * 64}])
    vault = FakeVault()
    with pytest.raises(ValueError, match="Conflicting"):
        vault_sync.push_specimens(vault, tmp_path)
    assert vault.writes == []


def test_empty_new_batch_preserves_every_existing_entry(tmp_path):
    old = encoded([entry(), entry("US_FED", "federal")])
    batch(tmp_path, [])
    vault = FakeVault(old)
    vault_sync.push_specimens(vault, tmp_path)
    assert vault.objects[POINTER] == old
    assert vault.writes == []


def test_repeated_same_batch_is_idempotent_and_duplicates_deduplicated(tmp_path):
    row = entry(keyed=False)
    batch(tmp_path, [row, row], [png()])
    vault = FakeVault()
    vault_sync.push_specimens(vault, tmp_path)
    first = vault.objects[POINTER]
    count = len(vault.writes)
    vault_sync.push_specimens(vault, tmp_path)
    assert vault.objects[POINTER] == first
    assert len(vault.writes) == count
    assert len(json.loads(first)["specimens"]) == 1


def test_checksum_failure_validates_entire_batch_before_any_upload(tmp_path):
    batch(
        tmp_path,
        [entry("MD", data=png(1), keyed=False), entry("MI", data=png(2), keyed=False)],
        [png(1)],
    )
    (tmp_path / (hashlib.sha256(png(2)).hexdigest() + ".png")).write_bytes(b"corrupt")
    old = encoded([entry()])
    vault = FakeVault(old)
    with pytest.raises(ValueError, match="integrity"):
        vault_sync.push_specimens(vault, tmp_path)
    assert vault.writes == []
    assert vault.objects[POINTER] == old


def test_non_png_cannot_be_published_despite_matching_hash(tmp_path):
    batch(tmp_path, [entry(data=b"not png", keyed=False)], [b"not png"])
    vault = FakeVault()
    with pytest.raises(ValueError, match="raster signature"):
        vault_sync.push_specimens(vault, tmp_path)
    assert vault.writes == []


def test_merged_index_budget_enforced_before_upload(tmp_path, monkeypatch):
    old = encoded([entry()])
    batch(tmp_path, [entry("MI", keyed=False)], [png()])
    vault = FakeVault(old)
    monkeypatch.setattr(vault_sync, "INDEX_LIMIT", 500)
    with pytest.raises(ValueError, match="budget"):
        vault_sync.push_specimens(vault, tmp_path)
    assert vault.objects[POINTER] == old
    assert vault.writes == []
