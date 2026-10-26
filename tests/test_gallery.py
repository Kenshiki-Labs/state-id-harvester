from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

import httpx
import pymupdf
import pytest

from state_id_harvester.gallery import GalleryJob, GalleryOptions, sha
from state_id_harvester.gallery_html import GalleryHTML, discover_images, srcset_urls
from state_id_harvester.gallery_import import import_browser_manifest
from state_id_harvester.gallery_raster import validate_raster
from state_id_harvester.network import Transport

PAGE = "https://dmv.ca.gov/gallery"


def png() -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 190), False)
    pix.clear_with(170)
    return bytes(pix.tobytes("png"))


def test_discovery_binds_picture_lazy_srcset_caption_table_and_ambiguous_dates() -> None:
    html = b"""<h2>2017 to 2020; replacement begins 2023</h2><table><tr><td>
    Driver license sample; no dates independently verified
    <picture><source srcset="/full.png 1200w, /small.jpg 1.5x">
    <img data-src="/lazy.png" alt="Specimen"></picture>
    <a href="/media/77">View image</a></td></tr></table>
    <figure><img src="/flat.jpg">
    <figcaption>Front/back attribution unverified</figcaption></figure>"""
    leads, rejected = discover_images(html, PAGE, 50)
    assert not rejected
    assert {row["url"] for row in leads} == {
        "https://dmv.ca.gov/" + path
        for path in ["full.png", "small.jpg", "lazy.png", "media/77", "flat.jpg"]
    }
    assert "2017 to 2020" in leads[0]["heading"]
    assert "2023" in leads[0]["heading"]
    assert "Driver license sample" in leads[0]["context"]
    assert "Front/back attribution unverified" in leads[-1]["caption"]
    assert all("issue_date" not in lead and "side" not in lead for lead in leads)


@pytest.mark.parametrize(
    "value",
    [
        "/a.png 0w",
        "/a.png 1..2x",
        "/a.png 1x extra",
        "data:image/png,https://dmv.ca.gov/fake.png 2x",
        ",/a.png",
    ],
)
def test_malformed_srcset_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        srcset_urls(value)


@pytest.mark.parametrize(
    "url",
    [
        "http://dmv.ca.gov/x.png",
        "https://dmv.ca.gov.evil.example/x.png",
        "https://127.0.0.1/x.png",
        "https://user:pass@dmv.ca.gov/x.png",
        "javascript:alert(1)",
        "https://cdn.example.com/x.png",
    ],
)
def test_unsafe_gallery_urls_never_become_fetch_leads(url: str) -> None:
    leads, rejected = discover_images(f'<img src="{url}">'.encode(), PAGE, 20)
    assert not leads
    assert len(rejected) == 1


def test_parser_structural_budget_blocks_deep_or_huge_dom() -> None:
    parser = GalleryHTML()
    with pytest.raises(ValueError, match="structural"):
        parser.feed("<div>" * 65)


def test_raster_validation_preserves_original_and_rejects_svg_or_html_masquerade() -> None:
    data = png()
    assert validate_raster(data, "image/png", 100000)["width"] == 300
    assert sha(data) == hashlib.sha256(data).hexdigest()
    for invalid in [b"<svg><script>bad()</script></svg>", b"<html>access denied</html>"]:
        with pytest.raises(ValueError, match="Unsupported raster"):
            validate_raster(invalid, "image/png", 100000)
    with pytest.raises(ValueError, match="Content-Type"):
        validate_raster(data, "image/jpeg", 100000)


def test_decompression_dimensions_checked_before_native_decoder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = bytearray(png())
    data[16:24] = struct.pack(">II", 50000, 50000)
    data[29:33] = struct.pack(">I", zlib.crc32(data[12:29]))
    called = False

    def forbidden(*args: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("Decoder must never see oversized frame")

    monkeypatch.setattr("state_id_harvester.gallery_raster.pymupdf.Pixmap", forbidden)
    oversized = bytes(data)
    with pytest.raises(ValueError, match="before decoding"):
        validate_raster(oversized, "image/png", 100000)
    assert not called


async def test_gallery_job_preserves_aliases_and_originals_without_pdf_or_cohort_updates(
    tmp_path: Path,
) -> None:
    original = png()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.path == "/gallery":
            return httpx.Response(
                200,
                text='<figure>2017/2023 ambiguous<img src="/one.png"><img src="/two.png"></figure>',
                headers={"content-type": "text/html"},
            )
        return httpx.Response(200, content=original, headers={"content-type": "image/png"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        job = GalleryJob(tmp_path / "gallery", GalleryOptions(), Transport(client, check_dns=False))
        await job.visit("CA", PAGE)
        result = job.finish()
    assert len(result["assets"]) == 1
    assert len(result["aliases"]) == 2
    asset = result["assets"][0]
    assert (tmp_path / "gallery" / asset["path"]).read_bytes() == original
    assert asset["altered"] is False
    assert asset["accepted_cohort"] is False
    assert asset["plate_composition"] == "unreviewed"
    assert all(
        row["parent_html_sha256"] == result["pages"][0]["sha256"] for row in result["aliases"]
    )
    assert not (tmp_path / "manifest.json").exists()
    assert not any("pdf" in url for url in requests)


async def test_gallery_uses_transport_robots_redirect_and_dns_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /blocked")
        if request.url.path == "/blocked":
            raise AssertionError("robots exclusion must precede request")
        if request.url.path == "/gallery":
            return httpx.Response(
                200, text='<img src="/redirect.png">', headers={"content-type": "text/html"}
            )
        return httpx.Response(302, headers={"location": "https://evil.example/private.png"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        job = GalleryJob(tmp_path, GalleryOptions(), Transport(client, check_dns=False))
        await job.visit("CA", "https://dmv.ca.gov/blocked")
        await job.visit("CA", PAGE)
        assert len(job.manifest["events"]) >= 2
        assert not job.manifest["assets"]
        assert not any("evil.example" in request for request in requests)
        monkeypatch.setattr(
            "state_id_harvester.network.socket.getaddrinfo",
            lambda *args: [(2, 1, 6, "", ("127.0.0.1", 443))],
        )
        protected = GalleryJob(tmp_path, GalleryOptions(), Transport(client))
        before = len(requests)
        await protected.visit("CA", PAGE)
        assert len(requests) == before
        assert protected.manifest["events"][0]["status"] == "failed"


async def test_gallery_limits_stream_and_persists_403_and_type_failures(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/forbidden":
            return httpx.Response(403)
        if request.url.path == "/huge":
            return httpx.Response(200, content=b"x" * 100, headers={"content-type": "image/png"})
        if request.url.path == "/gallery":
            return httpx.Response(
                200, text='<img src="/fake.png">', headers={"content-type": "text/html"}
            )
        return httpx.Response(
            200, content=b"<html>not a PNG</html>", headers={"content-type": "image/png"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        job = GalleryJob(
            tmp_path, GalleryOptions(max_image_bytes=50), Transport(client, check_dns=False)
        )
        await job.visit("CA", "https://dmv.ca.gov/forbidden")
        await job.image({"collection": "CA", "url": "https://dmv.ca.gov/huge"})
        await job.visit("CA", PAGE)
        result = job.finish()
    assert len(result["events"]) == 3
    assert not result["assets"]
    assert len(json.loads((tmp_path / "manifest.json").read_text())["events"]) == 3


async def test_browser_import_hashes_parent_and_images_and_rejects_traversal(
    tmp_path: Path,
) -> None:
    original = png()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    html = b'<h2>Unverified 2017 and 2023</h2><img src="/one.png">'
    (evidence / "source.html").write_bytes(html)
    (evidence / "one.png").write_bytes(original)
    record = {
        "url": "https://dmv.ca.gov/one.png",
        "asset_url": "https://dmv.ca.gov/one.png",
        "path": "one.png",
        "sha256": sha(original),
        "size_bytes": len(original),
        "headers": {"content-type": "image/png"},
        "altered": False,
        "accepted_cohort": True,
    }
    ledger = {
        "source_page_url": PAGE,
        "collection": "CA",
        "html_path": "source.html",
        "parent_html_sha256": sha(html),
        "images": [record, {**record, "path": "../escape.png"}, {**record, "sha256": "0" * 64}],
    }
    path = evidence / "import.json"
    path.write_text(json.dumps(ledger))
    async with httpx.AsyncClient() as client:
        job = GalleryJob(tmp_path / "gallery", GalleryOptions(), Transport(client))
        await import_browser_manifest(job, path)
        result = job.finish()
    assert len(result["assets"]) == 1
    assert result["assets"][0]["accepted_cohort"] is False
    assert len(result["events"]) == 2
    assert "network_not_replayed" in result["aliases"][0]["acquisition_method"]


def test_table_context_keeps_neighboring_date_columns_without_assigning_a_cohort() -> None:
    html = b'<table><tr><th>Issued 2017 to 2022</th><td><img src="/card.png"></td></tr></table>'
    leads, _ = discover_images(html, PAGE, 10)
    assert "Issued 2017 to 2022" in leads[0]["table_row_context"]
    assert "Issued 2017 to 2022" in leads[0]["table_context"]
    assert "cohort" not in leads[0]


def test_hostile_base_url_never_silently_changes_source_link_binding() -> None:
    from state_id_harvester.network import FetchError

    html = b'<base href="https://evil.example/"><img src="private.png">'
    with pytest.raises(FetchError):
        discover_images(html, PAGE, 10)


def test_jpeg_header_dimensions_and_native_decode_agree() -> None:
    pix = pymupdf.Pixmap(png())
    jpeg = bytes(pix.tobytes("jpeg"))
    assert validate_raster(jpeg, "image/jpeg", 100000)["height"] == 190


async def test_media_html_wrapper_is_bounded_and_eventually_discovers_a_raster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = png()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/gallery":
            return httpx.Response(
                200,
                text='<a href="/media/77">View image</a>',
                headers={"content-type": "text/html"},
            )
        if request.url.path == "/media/77":
            return httpx.Response(
                200, text='<img src="/full.png">', headers={"content-type": "text/html"}
            )
        return httpx.Response(200, content=original, headers={"content-type": "image/png"})

    monkeypatch.setitem(
        __import__(
            "state_id_harvester.gallery", fromlist=["HTML_GALLERY_SEEDS"]
        ).HTML_GALLERY_SEEDS,
        "CA",
        [PAGE],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        job = GalleryJob(tmp_path, GalleryOptions(max_pages=2), Transport(client, check_dns=False))
        await job.run(["CA"])
    assert len(job.manifest["pages"]) == 2
    assert len(job.manifest["assets"]) == 1
    assert job.manifest["events"][0]["status"] == "html_wrapper"


async def test_total_byte_budget_and_asset_request_budget_bound_the_job(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/gallery":
            return httpx.Response(
                200,
                text='<img src="/one.png"><img src="/two.png">',
                headers={"content-type": "text/html"},
            )
        return httpx.Response(200, content=png(), headers={"content-type": "image/png"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        job = GalleryJob(
            tmp_path,
            GalleryOptions(max_assets=1, max_total_bytes=100),
            Transport(client, check_dns=False),
        )
        await job.visit("CA", PAGE)
    assert job.remaining >= 0
    assert job.requested_assets == 1
    assert not job.manifest["assets"]
    assert any(event["status"] == "skipped" for event in job.manifest["events"])


async def test_cancelled_job_keeps_its_private_failure_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from state_id_harvester.gallery import harvest_images

    async def cancelled(job: GalleryJob, collections: list[str]) -> None:
        job.event("CA", PAGE, "failed", "operator_interrupted_fixture")
        raise asyncio.CancelledError

    monkeypatch.setattr(GalleryJob, "run", cancelled)
    options = GalleryOptions()
    with pytest.raises(asyncio.CancelledError):
        await harvest_images(["CA"], tmp_path, options)
    result = json.loads((tmp_path / "manifest.json").read_text())
    assert result["run_status"] == "interrupted"
    assert result["events"][0]["reason"] == "operator_interrupted_fixture"
    assert list((tmp_path / "runs").glob("*.json"))


def test_gallery_cli_runs_separately_and_refuses_to_overwrite_pdf_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from state_id_harvester import cli

    monkeypatch.chdir(tmp_path)
    calls: list[list[str]] = []

    async def harvest(
        collections: list[str], root: Path, options: GalleryOptions, imports: list[Path]
    ) -> dict[str, object]:
        calls.append(collections)
        assert root == tmp_path / "output/gallery"
        return {"assets": [], "aliases": [], "events": []}

    monkeypatch.setattr("state_id_harvester.gallery.harvest_images", harvest)
    args = cli.parser().parse_args(["harvest-images", "--states", "WA", "NY"])
    cli.run_gallery(args)
    assert calls == [["NY", "WA"]]
    assert "accepted cohorts: 0" in capsys.readouterr().out
    (tmp_path / "output/gallery/manifest.json").write_text('{"schema_version":1,"documents":[]}')
    with pytest.raises(ValueError, match="separate"):
        cli.run_gallery(args)
    empty_args = cli.parser().parse_args(["harvest-images"])
    with pytest.raises(ValueError, match="Choose"):
        cli.run_gallery(empty_args)


async def test_limited_fetch_budget_prioritizes_card_context_over_navigation(
    tmp_path: Path,
) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/gallery":
            return httpx.Response(
                200,
                text=(
                    '<img src="/logo.png"><h2>Driver license samples</h2>'
                    '<figure><img src="/card.png" alt="License specimen">'
                    "<figcaption>Unverified design examples</figcaption></figure>"
                ),
                headers={"content-type": "text/html"},
            )
        return httpx.Response(200, content=png(), headers={"content-type": "image/png"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        job = GalleryJob(tmp_path, GalleryOptions(max_assets=1), Transport(client, check_dns=False))
        await job.visit("CA", PAGE)
    assert "/card.png" in requested
    assert "/logo.png" not in requested
    assert job.manifest["assets"][0]["review_status"] == "unreviewed"


def test_opaque_specimen_table_link_outranks_id_related_editorial_photo() -> None:
    from state_id_harvester.gallery_html import lead_priority

    html = b"""<h2>ID card designs</h2><aside>
    <img src="/id-card-voter.jpg" alt="Polling volunteer checks ID card"></aside>
    <h2>License design types by year issued</h2><table><tr><td>Driver license sample</td>
    <td><a href="/media/77">View image</a></td></tr></table>"""
    leads, _ = discover_images(html, PAGE, 10)
    ranked = sorted(leads, key=lead_priority, reverse=True)
    assert ranked[0]["url"] == "https://dmv.ca.gov/media/77"


async def test_native_decoder_does_not_run_on_an_unsafe_background_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    current = threading.get_ident()

    def checked(data: bytes, media: str, pixels: int) -> dict[str, object]:
        assert threading.get_ident() == current
        return validate_raster(data, media, pixels)

    monkeypatch.setattr("state_id_harvester.gallery.validate_raster", checked)
    async with httpx.AsyncClient() as client:
        job = GalleryJob(tmp_path, GalleryOptions(), Transport(client))
        await job.asset(
            {"collection": "CA", "url": PAGE}, png(), PAGE, "image/png", "synthetic_test"
        )
    assert len(job.manifest["assets"]) == 1


async def populated_gallery(root: Path) -> dict[str, object]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/gallery":
            return httpx.Response(
                200,
                text='<h2>Specimen</h2><img src="/card.png">',
                headers={"content-type": "text/html"},
            )
        return httpx.Response(200, content=png(), headers={"content-type": "image/png"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        job = GalleryJob(root, GalleryOptions(), Transport(client, check_dns=False))
        await job.visit("CA", PAGE)
        return job.finish()


async def test_later_403_keeps_verified_inventory_and_previous_last_seen(tmp_path: Path) -> None:
    from state_id_harvester.gallery_verify import verify_gallery

    first = await populated_gallery(tmp_path)
    original_receipt = (tmp_path / "manifest.json").read_bytes()

    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if request.url.path == "/robots.txt" else 403)

    async with httpx.AsyncClient(transport=httpx.MockTransport(blocked)) as client:
        job = GalleryJob(tmp_path, GalleryOptions(), Transport(client, check_dns=False))
        await job.visit("CA", PAGE)
        second = job.finish()
    assert second["assets"] == first["assets"]
    assert second["pages"] == first["pages"]
    assert second["aliases"] == first["aliases"]
    assert second["run_observations"] == {"assets": 0, "pages": 0, "aliases": 0}
    assert second["events"][0]["reason"] == "http_status_403"
    assert len(second["events"]) == 1
    assert second["inventory_parent_run_id"] == first["run_id"]
    assert (tmp_path / "runs" / f"{first['run_id']}.json").read_bytes() == original_receipt
    assert verify_gallery(tmp_path) == []


async def test_successful_refetch_updates_last_seen_without_duplicate_inventory(
    tmp_path: Path,
) -> None:
    first = await populated_gallery(tmp_path)
    first_seen = first["assets"][0]["first_seen_at"]
    last_seen = first["assets"][0]["last_seen_at"]
    second = await populated_gallery(tmp_path)
    assert len(second["assets"]) == 1
    assert len(second["aliases"]) == 1
    assert len(second["pages"]) == 1
    assert second["assets"][0]["first_seen_at"] == first_seen
    assert second["assets"][0]["last_seen_at"] >= last_seen
    assert second["run_observations"] == {"assets": 1, "pages": 1, "aliases": 1}


async def test_tampered_prior_original_fails_closed_without_replacing_receipt(
    tmp_path: Path,
) -> None:
    from state_id_harvester.gallery_verify import verify_gallery

    first = await populated_gallery(tmp_path)
    receipt = (tmp_path / "manifest.json").read_bytes()
    (tmp_path / first["assets"][0]["path"]).write_bytes(b"tampered")
    assert verify_gallery(tmp_path)
    options = GalleryOptions()
    async with httpx.AsyncClient() as client:
        transport = Transport(client)
        with pytest.raises(ValueError, match="failed verification"):
            GalleryJob(tmp_path, options, transport)
    assert (tmp_path / "manifest.json").read_bytes() == receipt


@pytest.mark.parametrize(
    "change",
    [
        "alias_asset",
        "alias_url",
        "alias_parent",
        "page_bytes",
        "dimensions",
        "path_escape",
        "claim_accepted",
        "malformed_json",
        "malformed_run_id",
    ],
)
async def test_verify_images_rejects_broken_hashes_paths_dimensions_and_bindings(
    tmp_path: Path, change: str
) -> None:
    from state_id_harvester.gallery_verify import verify_gallery

    data = await populated_gallery(tmp_path)
    if change == "alias_asset":
        data["aliases"][0]["asset_sha256"] = "0" * 64
    elif change == "alias_url":
        data["aliases"][0]["url"] = "https://dmv.ca.gov/not-in-source.png"
    elif change == "alias_parent":
        data["aliases"][0]["parent_html_sha256"] = "0" * 64
    elif change == "page_bytes":
        (tmp_path / data["pages"][0]["path"]).write_bytes(b"modified page")
    elif change == "dimensions":
        data["assets"][0]["width"] += 1
    elif change == "path_escape":
        data["assets"][0]["path"] = "../outside.png"
    elif change == "claim_accepted":
        data["assets"][0]["accepted_cohort"] = True
    elif change == "malformed_run_id":
        data["run_id"] = {"malformed": True}
    else:
        (tmp_path / "manifest.json").write_text("not JSON")
    if change != "malformed_json":
        (tmp_path / "manifest.json").write_text(json.dumps(data))
    assert verify_gallery(tmp_path)


async def test_verify_images_cli_verifies_gallery_instead_of_pdf_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from state_id_harvester import cli

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "output/gallery"
    await populated_gallery(root)
    args = cli.parser().parse_args(["verify-images"])
    cli.run_verify_images(args)
    assert "source bindings verify" in capsys.readouterr().out
    (root / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="Gallery verification failed"):
        cli.run_verify_images(args)


def test_srcset_ascii_validation_does_not_widen_to_unicode_digits() -> None:
    assert srcset_urls("/one.png 1200w, /two.png 1.5x") == ["/one.png", "/two.png"]
    with pytest.raises(ValueError, match="Invalid srcset"):
        srcset_urls("/one.png ١٢٠٠w")
