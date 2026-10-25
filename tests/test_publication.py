from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import tarfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest


def script(name: str):
    spec = importlib.util.spec_from_file_location(name, Path("scripts") / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


exporter = script("build_public_catalog")
guard = script("check_publication")
vault_sync = script("vault_sync")
unpacker = script("unpack_library")


def manifest() -> dict:
    return {
        "generated_at": "2026-10-25T00:00:00Z",
        "run_id": "test-run",
        "raw_text": "PRIVATE DOCUMENT CONTENT",
        "documents": [
            {
                "title": "Official research guide",
                "page_count": 2,
                "relevance": "candidate",
                "relevance_reason": "PRIVATE DOCUMENT CONTENT",
                "download": {
                    "source": {
                        "discovery_jurisdiction": "WA",
                        "link_text": "PRIVATE DOCUMENT CONTENT",
                    },
                    "final_url": "https://example.gov/guide.pdf",
                    "sha256": "a" * 64,
                    "retrieved_at": "2026-10-25T00:00:00Z",
                    "publisher_host": "example.gov",
                    "publisher_jurisdiction": "WA",
                },
                "assets": [
                    {"kind": "page_render", "page_number": 1, "path": "private/image.png"},
                    {"kind": "page_render", "page_number": 1, "path": "private/second-tile.png"},
                    {"kind": "text", "page_number": 1, "text": "PRIVATE DOCUMENT CONTENT"},
                ],
                "future_unknown_payload": {"base64_image": "PRIVATE DOCUMENT CONTENT"},
            }
        ],
    }


def catalog() -> dict:
    # A stale source-count claim must not override actual retained manifest assets.
    return exporter.public_catalog(
        manifest(), [{"jurisdiction": "WA", "source_documents": 999}], []
    )


def test_export_keeps_citations_and_counts_without_unknown_private_content() -> None:
    result = catalog()
    encoded = json.dumps(result)
    assert "PRIVATE DOCUMENT CONTENT" not in encoded
    assert "private/image.png" not in encoded
    assert len(result["jurisdictions"]) == 51
    assert result["stats"]["sources"] == 1
    assert result["stats"]["rendered_pages"] == 1  # Two tiles are one source page.
    assert result["stats"]["accepted_cohorts"] == 0
    assert result["stats"]["jurisdictions_with_sources"] == 1
    washington = next(r for r in result["jurisdictions"] if r["code"] == "WA")
    assert washington["review_status"] == "unreviewed"
    assert washington["sources"][0]["sha256"] == "a" * 64
    assert washington["sources"][0]["url"] == "https://example.gov/guide.pdf"


@pytest.mark.parametrize(
    "url",
    ["http://example.gov/a.pdf", "data:image/png;base64,abc", "https://key:secret@example.gov/a"],
)
def test_export_refuses_credential_urls_or_embedded_source_payload(url: str) -> None:
    document = manifest()["documents"][0]
    document["download"]["final_url"] = url
    with pytest.raises(ValueError, match="credential-free HTTPS"):
        exporter.citation(document)


def test_valid_metadata_and_independent_geometry_pass(tmp_path: Path) -> None:
    (tmp_path / "catalog.json").write_text(json.dumps(catalog()))
    (tmp_path / "wireframe.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-cadastre-diagram="independent">'
        '<rect x="0" y="0" width="85.6" height="53.98"/></svg>'
    )
    assert guard.inspect_public_tree(tmp_path) == []


def test_wireframe_contains_only_reviewed_rectangles_and_removes_superseded_files(
    tmp_path: Path,
) -> None:
    cohort = {
        "cohort_id": "WA_REVIEWED_EXAMPLE",
        "orientation": "horizontal",
        "zones": [{"bbox_uv": [0.1, 0.2, 0.3, 0.4], "name": "PRIVATE LABEL"}],
        "raw_image": "PRIVATE IMAGE",
    }
    exporter.write_wireframes(tmp_path, [cohort])
    wireframe = tmp_path / "WA_REVIEWED_EXAMPLE.svg"
    assert "PRIVATE" not in wireframe.read_text()
    assert 'x="856.0000"' in wireframe.read_text()
    assert guard.inspect_public_tree(tmp_path) == []
    exporter.write_wireframes(tmp_path, [])
    assert not wireframe.exists()


@pytest.mark.parametrize(
    "filename,content",
    [
        ("deep/nested/specimen.PNG", b"image"),
        ("pretend.json", b'{"innocent":"%PDF-1.7"}'),
        ("pretend.json", b"\xff\x80PRIVATE"),
        ("pretend.json", b'{"null":"\x00"}'),
        ("extra.heic", b"unrecognized media"),
        ("raw_source.txt", b"security callout from an extracted document"),
        ("raw_source.md", b"security callout from an extracted document"),
        ("extra.json", b'{"text":"raw callout"}'),
        ("inline.html", b'<img src="data:image/png;base64,iVBORw0KGgo=">'),
        ("inline.html", b'<img src="https://example.gov/specimen.png">'),
        ("inline.css", b'.plate{background:url("https://example.gov/specimen.png")}'),
        ("inline.html", b'<img src="data&#58;image/png;base64,iVBORw0KGgo=">'),
        ("inline.css", rb".plate{background:url(d\61 ta\3a image/png;base64,iVBORw0KGgo=)}"),
        (
            "inline.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg" data-cadastre-diagram="independent"><image href="https://example.gov/specimen.png"/></svg>',
        ),
        (
            "inline.svg",
            b'<svg data-cadastre-diagram="independent">'
            b'<foreignObject><img src="x"/></foreignObject></svg>',
        ),
        (
            "inline.svg",
            b'<svg data-cadastre-diagram="independent"><rect onclick="alert(1)"/></svg>',
        ),
        (
            "inline.svg",
            b'<svg data-cadastre-diagram="independent"><path fill="url(#embedded)"/></svg>',
        ),
        ("inline.svg", b'<svg><path d="M0 0 L1 1"/></svg>'),
    ],
)
def test_public_guard_rejects_counterexample_media_and_payloads(
    tmp_path: Path, filename: str, content: bytes
) -> None:
    path = tmp_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    assert guard.inspect_public_tree(tmp_path), filename


@pytest.mark.parametrize("target", ["source", "counts", "row", "top"])
def test_public_guard_rejects_raw_prose_injected_into_metadata(tmp_path: Path, target: str) -> None:
    data = copy.deepcopy(catalog())
    row = data["jurisdictions"][-4]  # The exact row identity does not affect the attack.
    if target == "source":
        next(r for r in data["jurisdictions"] if r["sources"])["sources"][0]["ocr_text"] = (
            "private source prose"
        )
    elif target == "counts":
        row["counts"]["raw_callout"] = "private source prose"
    elif target == "row":
        row["feature_evidence"] = [{"text": "private source prose"}]
    else:
        data["new_payload"] = {"image": "hidden source media"}
    (tmp_path / "catalog.json").write_text(json.dumps(data))
    assert guard.inspect_public_tree(tmp_path)


def test_public_guard_rejects_source_symlink_and_fake_bundled_font(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.write_bytes(b"source media")
    public = tmp_path / "public"
    public.mkdir()
    (public / "catalog.json").symlink_to(private)
    astro = public / "_astro"
    astro.mkdir()
    (astro / "specimen.woff2").write_bytes(b"not a registered brand font")
    errors = guard.inspect_public_tree(public, bundled=True)
    assert any("symlink" in error for error in errors)
    assert any("woff2" in error for error in errors)


def archive(
    directory: Path,
    *,
    name: str = "library-001.tar.gz",
    member: str = "WA/raw/source.pdf",
    symlink: bool = False,
) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    with tarfile.open(path, "w:gz") as target:
        info = tarfile.TarInfo(member)
        if symlink:
            info.type = tarfile.SYMTYPE
            info.linkname = "../../outside"
            target.addfile(info)
        else:
            info.size = len(b"private source")
            target.addfile(info, BytesIO(b"private source"))
    return {
        "name": name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


@pytest.mark.parametrize(
    "bad_member,symlink", [("../../outside", False), ("/absolute/path", False), ("safe/link", True)]
)
def test_restore_validates_all_parts_before_writing(
    tmp_path: Path, bad_member: str, symlink: bool
) -> None:
    incoming = tmp_path / "incoming"
    parts = [
        archive(incoming),
        archive(incoming, name="library-002.tar.gz", member=bad_member, symlink=symlink),
    ]
    (incoming / "library-index.json").write_text(json.dumps(parts))
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="escapes|regular files"):
        unpacker.restore_library(incoming, output)
    assert not output.exists()


@pytest.mark.parametrize("attack", ["missing", "part_symlink", "unsafe_name", "duplicate", "empty"])
def test_restore_rejects_missing_and_unsafe_archive_parts(tmp_path: Path, attack: str) -> None:
    incoming = tmp_path / "incoming"
    part = archive(incoming)
    parts = [part]
    if attack == "missing":
        (incoming / part["name"]).unlink()
    elif attack == "part_symlink":
        target = tmp_path / "private.tar.gz"
        (incoming / part["name"]).rename(target)
        (incoming / part["name"]).symlink_to(target)
    elif attack == "unsafe_name":
        part["name"] = "../private.tar.gz"
    elif attack == "duplicate":
        parts.append(part.copy())
    else:
        parts = []
    (incoming / "library-index.json").write_text(json.dumps(parts))
    with pytest.raises(ValueError):
        unpacker.restore_library(incoming, tmp_path / "output")


@pytest.mark.parametrize(
    "key",
    [
        "specimens/../secret",
        "specimens//x",
        "https://evil/x",
        "other/file",
        "snapshots/a?token=x",
        "snapshots/./part",
    ],
)
def test_private_transport_rejects_unsafe_keys(key: str) -> None:
    with pytest.raises(ValueError):
        vault_sync.safe_key(key)


def mock_vault(monkeypatch: pytest.MonkeyPatch, objects: dict[str, bytes]):
    client_class = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-secret"
        key = request.url.path.removeprefix("/internal/objects/")
        if request.method == "PUT":
            assert (
                request.headers["x-content-sha256"] == hashlib.sha256(request.content).hexdigest()
            )
            objects[key] = request.content
            return httpx.Response(201)
        return httpx.Response(200, content=objects[key]) if key in objects else httpx.Response(404)

    monkeypatch.setattr(
        vault_sync.httpx,
        "Client",
        lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs),
    )
    return vault_sync.Vault("https://vault.example", "test-secret")


def test_private_snapshot_round_trip_splits_checksums_and_restores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    incoming = tmp_path / "incoming"
    part = archive(incoming)
    (incoming / "library-index.json").write_text(json.dumps([part]))
    objects: dict[str, bytes] = {}
    vault = mock_vault(monkeypatch, objects)
    vault_sync.push_snapshot(vault, incoming, chunk_bytes=64)
    index = json.loads(objects["indexes/latest-snapshot.json"])
    assert len(index["archives"][0]["chunks"]) > 1
    assert all(len(value) <= 64 for key, value in objects.items() if ".part-" in key)
    output = tmp_path / "output"
    vault_sync.pull_snapshot(vault, tmp_path / "restore", output)
    assert (output / "WA/raw/source.pdf").read_bytes() == b"private source"
    vault.close()


def test_private_restore_rejects_corrupted_chunk_before_unpacking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    incoming = tmp_path / "incoming"
    part = archive(incoming)
    (incoming / "library-index.json").write_text(json.dumps([part]))
    objects: dict[str, bytes] = {}
    vault = mock_vault(monkeypatch, objects)
    vault_sync.push_snapshot(vault, incoming)
    index = json.loads(objects["indexes/latest-snapshot.json"])
    chunk = index["archives"][0]["chunks"][0]
    objects[chunk["key"]] = b"corrupted"
    with pytest.raises(ValueError, match="integrity"):
        vault_sync.pull_snapshot(vault, tmp_path / "restore", tmp_path / "output")
    assert not (tmp_path / "output").exists()
    vault.close()


def test_visible_marking_preserves_original_pixels_and_records_padding() -> None:
    import cv2
    import numpy as np

    original = np.zeros((100, 200, 3), dtype=np.uint8)
    original[:, :, 1] = np.arange(200)
    marked = vault_sync.marked_reference(original)
    assert marked is not None
    data, transform = marked
    decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    offset = transform["offset_x_px"]
    assert np.array_equal(decoded[:100, offset : offset + 200], original)
    assert decoded.shape == (210, 900, 3)
    assert transform["scale_x"] == transform["scale_y"] == 1
    assert np.count_nonzero(decoded[100:] > 240) > 100  # The footer contains visible lettering.


def test_candidate_dimension_budget_is_checked_before_decode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import struct

    data = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 100_000, 100_000)
    (tmp_path / "bomb.png").write_bytes(data)
    asset = SimpleNamespace(path="bomb.png", sha256=hashlib.sha256(data).hexdigest())

    def forbidden_decode(*args, **kwargs):
        pytest.fail("An oversized source reached the image decoder")

    monkeypatch.setattr("cv2.imdecode", forbidden_decode)
    with pytest.raises(ValueError, match="pixel budget"):
        vault_sync.read_candidate_image(tmp_path, asset)


def test_visual_publication_is_absent_from_the_collection_job() -> None:
    workflow = Path(".github/workflows/harvest.yml").read_text()
    assert "vault_sync.py push" in workflow
    assert "check_publication.py" in workflow
    assert "gh release create" not in workflow
    assert "uses: actions/upload-artifact" not in workflow
