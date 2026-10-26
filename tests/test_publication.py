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

from state_id_harvester.extract import extract
from state_id_harvester.models import Manifest, Options, Source


def script(name: str):
    spec = importlib.util.spec_from_file_location(name, Path("scripts") / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
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


@pytest.mark.parametrize("state", ["ME", "MD", "MI", "US_FED"])
def test_public_guard_allows_only_worker_resolved_reference_images(
    tmp_path: Path, state: str
) -> None:
    (tmp_path / "index.html").write_text(
        f'<img src="/v1/specimens/{state}/native-xref_123" alt="Marked research reference" '
        'loading="lazy" decoding="async" width="600" height="400" class="reference"/>'
    )
    assert guard.inspect_public_tree(tmp_path) == []


@pytest.mark.parametrize(
    "markup",
    [
        '<img src="https://cadastre.kenshikilabs.com/v1/specimens/MI/example">',
        '<img src="//cadastre.kenshikilabs.com/v1/specimens/MI/example">',
        '<img src="/v1/specimens/mi/example">',
        '<img src="/v1/specimens/MI/../source">',
        '<img src="/v1/specimens/MI/%2e%2e">',
        '<img src="/v1/specimens/MI/example?key=original">',
        '<img src="/v1/specimens/MI/example#raw">',
        '<img src="/v1/specimens/MI/example.pdf">',
        '<img src="/v1/specimens/MI/">',
        '<img src="/v1/specimens/MI/' + "a" * 151 + '">',
        '<img src="/v1/specimens/MI/example" src="/original.png">',
        '<img src="/v1/specimens/MI/example" srcset="/original.png 2x">',
        '<img src="/v1/specimens/MI/example" onerror="this.src=\'/original.png\'">',
        '<img src="/v1/specimens/MI/example" style="background:url(/original.png)">',
        '<img src="/v1/specimens/MI/example" lowsrc="/original.png">',
        '<picture><img src="/v1/specimens/MI/example"></picture>',
        '<svg><image href="/v1/specimens/MI/example"/></svg>',
        '<IMG SRC="/original.png">',
    ],
)
def test_public_guard_rejects_reference_image_delivery_bypasses(
    tmp_path: Path, markup: str
) -> None:
    (tmp_path / "index.html").write_text(markup)
    assert guard.inspect_public_tree(tmp_path)


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


def raster_frame(image_format: str, width: int, height: int) -> bytes:
    import struct
    import zlib

    if image_format == "jpeg":
        return b"\xff\xd8\xff\xc0" + struct.pack(">HBHHBBBB", 11, 8, height, width, 1, 1, 0x11, 0)
    body = b"IHDR" + struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0d" + body + struct.pack(">I", zlib.crc32(body))


@pytest.mark.parametrize("image_format", ["png", "jpeg"])
@pytest.mark.parametrize("dimensions", [(10000, 10000), (0, 100), (20001, 1)])
def test_candidate_dimension_budget_is_checked_before_decode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, image_format: str, dimensions: tuple[int, int]
) -> None:
    data = raster_frame(image_format, *dimensions)
    (tmp_path / "bomb.bin").write_bytes(data)
    asset = SimpleNamespace(path="bomb.bin", sha256=hashlib.sha256(data).hexdigest())

    def forbidden_decode(*args, **kwargs):
        pytest.fail("An oversized source reached the image decoder")

    monkeypatch.setattr("cv2.imdecode", forbidden_decode)
    with pytest.raises(ValueError, match="pixel budget"):
        vault_sync.read_candidate_image(tmp_path, asset)


@pytest.mark.parametrize(
    "data,reason",
    [
        (b"<svg><image/></svg>", "Unsupported raster"),
        (b"<!doctype html><img src='pretend.png'>", "Unsupported raster"),
        (b"RIFF\0\0\0\0WEBP", "Unsupported raster"),
        (b"\xff\xd8\xff\xe1\xff\xff" + b"x" * 65533, "header budget"),
        (raster_frame("png", 100, 100)[:-1] + b"\xff", "checksum mismatch"),
    ],
)
def test_candidate_unsupported_or_unbounded_headers_never_reach_decoder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: bytes, reason: str
) -> None:
    path = tmp_path / "pretend.png"
    path.write_bytes(data)
    asset = SimpleNamespace(path=path.name, sha256=hashlib.sha256(data).hexdigest())
    monkeypatch.setattr("cv2.imdecode", lambda *args: pytest.fail("Unsafe header reached decoder"))
    with pytest.raises(ValueError, match=reason):
        vault_sync.read_candidate_image(tmp_path, asset)


def test_candidate_byte_budget_is_checked_before_hash_or_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "large.jpg"
    with path.open("wb") as stream:
        stream.truncate(50_000_001)
    asset = SimpleNamespace(path=path.name, sha256="not-read")
    monkeypatch.setattr(
        "cv2.imdecode", lambda *args: pytest.fail("Oversized bytes reached decoder")
    )
    with pytest.raises(ValueError, match="byte budget"):
        vault_sync.read_candidate_image(tmp_path, asset)


def test_candidate_decoded_dimensions_must_match_checked_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np

    data = raster_frame("jpeg", 100, 100)
    (tmp_path / "mismatch.jpg").write_bytes(data)
    asset = SimpleNamespace(path="mismatch.jpg", sha256=hashlib.sha256(data).hexdigest())
    monkeypatch.setattr("cv2.imdecode", lambda *args: np.zeros((101, 100, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="dimensions disagree"):
        vault_sync.read_candidate_image(tmp_path, asset)


def test_native_jpeg_proposal_prepares_png_derivative_without_changing_original(
    tmp_path: Path,
) -> None:
    import cv2
    import numpy as np
    import pymupdf

    from state_id_harvester.models import Download

    source = tmp_path / "collection"
    path = source / "WA/raw_pdfs/native-jpeg.pdf"
    path.parent.mkdir(parents=True)
    pixels = np.zeros((190, 300, 3), dtype=np.uint8)
    pixels[:, :, 1] = np.arange(300, dtype=np.uint16) % 256
    ok, encoded = cv2.imencode(".jpg", pixels)
    assert ok
    jpeg = encoded.tobytes()
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((70, 130), "Driver license SPECIMEN - microprinting and ultraviolet")
        page.insert_image(pymupdf.Rect(70, 160, 370, 350), stream=jpeg)
        pdf.save(path)
    download = Download(
        source=Source(
            discovery_jurisdiction="WA",
            url="https://dol.wa.gov/test.pdf",
            discovered_via="synthetic_mechanics_test",
        ),
        final_url="https://dol.wa.gov/test.pdf",
        retrieved_at="2026-10-25T00:00:00Z",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        size_bytes=path.stat().st_size,
        path=path.relative_to(source).as_posix(),
        content_type="application/pdf",
        publisher_host="dol.wa.gov",
        publisher_jurisdiction="WA",
    )
    document = extract(download, str(source), Options(dpi=72, max_render_pages=1))
    candidate = next(asset for asset in document.assets if asset.kind == "card_candidate")
    original = source / candidate.path
    assert original.read_bytes() == jpeg
    manifest = Manifest(
        generated_at="2026-10-25T00:00:00Z",
        run_id="jpeg-test",
        source_revision="test",
        requested_jurisdictions=["WA"],
        options=Options(),
        documents=[document],
        reviews=[],
    )
    (source / "manifest.json").write_text(manifest.model_dump_json())
    destination = tmp_path / "prepared"
    items = vault_sync.prepare_specimens(source, destination, 1, federal_limit=0)
    assert len(items) == 1
    item = items[0]
    assert item["original_asset_sha256"] == hashlib.sha256(jpeg).hexdigest()
    assert item["source_sha256"] == download.sha256
    assert item["review_status"] == "reference_only"
    assert item["transform"]["footer_height_px"] == 110
    prepared = (destination / f"{item['asset_sha256']}.png").read_bytes()
    assert prepared.startswith(b"\x89PNG\r\n\x1a\n")
    decoded = cv2.imdecode(np.frombuffer(prepared, dtype=np.uint8), cv2.IMREAD_COLOR)
    native = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    offset = item["transform"]["offset_x_px"]
    assert np.array_equal(decoded[:190, offset : offset + 300], native)
    assert decoded.shape == (300, 900, 3)
    assert original.read_bytes() == jpeg
    assert hashlib.sha256(path.read_bytes()).hexdigest() == download.sha256


@pytest.mark.parametrize("attack", ["parent_traversal", "symlink"])
def test_private_preparation_refuses_assets_outside_its_manifest_root(
    tmp_path: Path, attack: str
) -> None:
    source = tmp_path / "collection"
    source.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private image outside the collection")
    if attack == "symlink":
        (source / "linked.png").symlink_to(outside)
        relative = "linked.png"
    else:
        relative = "../outside.png"
    asset = SimpleNamespace(path=relative, sha256=hashlib.sha256(outside.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="symlink|escapes"):
        vault_sync.read_candidate_image(source, asset)


def test_visual_publication_is_absent_from_the_collection_job() -> None:
    workflow = Path(".github/workflows/harvest.yml").read_text()
    assert "vault_sync.py push" in workflow
    assert "check_publication.py" in workflow
    assert "gh release create" not in workflow
    assert "uses: actions/upload-artifact" not in workflow


def test_private_preparation_includes_quarantined_federal_plates_without_id1_claims(
    tmp_path: Path,
) -> None:
    from test_extraction import fixture_pdf

    source = tmp_path / "collection"
    state_download = fixture_pdf(source)
    state_doc = extract(state_download, str(source), Options(dpi=72, max_render_pages=1))
    federal = source / "federal"
    original = fixture_pdf(federal)
    federal_source = Source(
        discovery_jurisdiction="US_FED", url=original.source.url, discovered_via="synthetic_test"
    )
    federal_download = original.model_copy(update={"source": federal_source})
    federal_doc = extract(federal_download, str(federal), Options(dpi=72, max_render_pages=1))
    federal_doc = federal_doc.model_copy(update={"relevance": "quarantined"})
    for root, code, document in [(source, "CA", state_doc), (federal, "US_FED", federal_doc)]:
        manifest = Manifest(
            generated_at="2026-10-25T00:00:00Z",
            run_id="test",
            source_revision="test",
            requested_jurisdictions=[code],
            options=Options(),
            documents=[document],
            reviews=[],
        )
        (root / "manifest.json").write_text(manifest.model_dump_json())
    destination = tmp_path / "prepared"
    items = vault_sync.prepare_specimens(source, destination, 1, federal_limit=1)
    assert len(items) == 2
    federal_item = next(item for item in items if item["state"] == "US_FED")
    assert federal_item["reference_kind"] == "page_plate"
    assert federal_item["credential_format"] == "unclassified"
    assert federal_item["source_relevance"] == "quarantined"
    assert federal_item["depicted_jurisdiction"] is None
    assert federal_item["review_status"] == "reference_only"
    assert federal_item["source_sha256"] == federal_download.sha256
    assert (destination / f"{federal_item['asset_sha256']}.png").is_file()


@pytest.mark.parametrize("code", ["WA", "AK", "HI", "DC"])
def test_allows_only_named_vector_state_artwork_in_public_html(code):
    markup = f'<img src="/artwork/states/{code}.svg" alt="" width="80" height="80" loading="lazy">'
    assert not guard.has_unapproved_html_image(markup)


@pytest.mark.parametrize(
    "source",
    [
        "/artwork/states/ZZ.svg",
        "/artwork/states/PR.svg",
        "/artwork/states/WA.png",
        "/artwork/states/../WA.svg",
        "/artwork/states/%57A.svg",
        "/artwork/states/WA.svg?source=private",
        "https://example.gov/artwork/states/WA.svg",
        "//example.gov/artwork/states/WA.svg",
    ],
)
def test_state_artwork_does_not_allow_other_static_or_external_images(source):
    assert guard.has_unapproved_html_image(f'<img src="{source}" alt="">')


def test_state_artwork_does_not_allow_active_image_attributes_or_embedded_rasters(tmp_path):
    assert guard.has_unapproved_html_image(
        '<img src="/artwork/states/WA.svg" alt="" onerror="alert(1)">'
    )
    artwork = tmp_path / "artwork" / "states" / "WA.svg"
    artwork.parent.mkdir(parents=True)
    artwork.write_text('<svg data-cadastre-diagram="independent"><image href="private.png"/></svg>')
    assert guard.inspect_public_tree(tmp_path)
