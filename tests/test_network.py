from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from state_id_harvester.models import Options, Source
from state_id_harvester.network import FetchError, Transport, official_url


class Chunks(httpx.AsyncByteStream):
    def __init__(self, parts: list[bytes]) -> None:
        self.parts = parts

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for part in self.parts:
            yield part


@pytest.mark.parametrize(
    "url",
    [
        "http://dmv.ca.gov/a.pdf",
        "https://dmv.ca.gov.evil.com/a.pdf",
        "https://user:pass@dmv.ca.gov/a.pdf",
        "https://127.0.0.1/a.pdf",
        "https://dmv.ca.gov:8443/a.pdf",
        "https://example.org/a.pdf",
    ],
)
def test_official_policy_rejects_unsafe_hosts(url: str) -> None:
    with pytest.raises(FetchError):
        official_url(url)


async def test_split_pdf_signature_and_endpoint_without_suffix(tmp_path: Path) -> None:
    payload = b"%PDF-1.7\n" + b"x" * 25_000

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            stream=Chunks([b"%P", b"DF-1.7\n", b"x" * 25_000]),
            headers={"Content-Type": "application/octet-stream"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await Transport(client, check_dns=False).download(
            Source(
                discovery_jurisdiction="TX",
                url="https://www.dps.texas.gov/form.ashx?id=1",
                discovered_via="test",
            ),
            tmp_path,
            Options(),
        )
    assert (tmp_path / result.path).read_bytes() == payload
    assert result.publisher_jurisdiction == "TX"
    assert result.publisher_host == "www.dps.texas.gov"


async def test_redirect_is_checked_before_request(tmp_path: Path) -> None:
    visited: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"Location": "https://localhost/secret"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FetchError):
            await Transport(client, check_dns=False).download(
                Source(
                    discovery_jurisdiction="CA",
                    url="https://dmv.ca.gov/a.pdf",
                    discovered_via="test",
                ),
                tmp_path,
                Options(),
            )
    assert not any("localhost" in u for u in visited)
    assert not list(tmp_path.rglob(".download-*"))


async def test_stream_limit_cleans_partial_download(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, stream=Chunks([b"%PDF-1.7\n", b"x" * 2000]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FetchError, match="byte limit"):
            await Transport(client, check_dns=False).download(
                Source(
                    discovery_jurisdiction="CA",
                    url="https://dmv.ca.gov/a.pdf",
                    discovered_via="test",
                ),
                tmp_path,
                Options(max_pdf_bytes=1024),
            )
    assert not list(tmp_path.rglob("*.pdf"))
    assert not list(tmp_path.rglob(".download-*"))


async def test_robots_disallow_is_honored(tmp_path: Path) -> None:
    visited: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FetchError, match="robots"):
            await Transport(client, check_dns=False).download(
                Source(
                    discovery_jurisdiction="CA",
                    url="https://dmv.ca.gov/private/a.pdf",
                    discovered_via="test",
                ),
                tmp_path,
                Options(),
            )
    assert visited == ["/robots.txt"]
