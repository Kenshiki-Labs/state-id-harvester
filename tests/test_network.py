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
        transport = Transport(client, check_dns=False)
        source = Source(
            discovery_jurisdiction="CA", url="https://dmv.ca.gov/a.pdf", discovered_via="test"
        )
        options = Options()
        with pytest.raises(FetchError):
            await transport.download(source, tmp_path, options)
    assert not any("localhost" in u for u in visited)
    assert not list(tmp_path.rglob(".download-*"))


async def test_stream_limit_cleans_partial_download(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, stream=Chunks([b"%PDF-1.7\n", b"x" * 2000]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client, check_dns=False)
        source = Source(
            discovery_jurisdiction="CA", url="https://dmv.ca.gov/a.pdf", discovered_via="test"
        )
        options = Options(max_pdf_bytes=1024)
        with pytest.raises(FetchError, match="byte limit"):
            await transport.download(source, tmp_path, options)
    assert not list(tmp_path.rglob("*.pdf"))
    assert not list(tmp_path.rglob(".download-*"))


async def test_robots_disallow_is_honored(tmp_path: Path) -> None:
    visited: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client, check_dns=False)
        source = Source(
            discovery_jurisdiction="CA",
            url="https://dmv.ca.gov/private/a.pdf",
            discovered_via="test",
        )
        options = Options()
        with pytest.raises(FetchError, match="robots"):
            await transport.download(source, tmp_path, options)
    assert visited == ["/robots.txt"]


@pytest.mark.parametrize(
    "location",
    [
        "http://dmv.ca.gov/next.pdf",
        "https://dmv.ca.gov.evil.example/next.pdf",
        "https://user:password@dmv.ca.gov/next.pdf",
        "https://dmv.ca.gov:8443/next.pdf",
        "https://dmv.ca.gov:notaport/next.pdf",
        "https://[broken/next.pdf",
    ],
)
async def test_redirect_policy_rejects_before_following(location: str) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": location})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client, check_dns=False)
        with pytest.raises((FetchError, ValueError, httpx.RemoteProtocolError)):
            await transport.bytes("https://dmv.ca.gov/start")
    assert requests == ["https://dmv.ca.gov/start"]


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "fc00::1", "224.0.0.1"]
)
async def test_dns_policy_rejects_nonpublic_addresses(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *_: [(2, 1, 6, "", (address, 443))])
    async with httpx.AsyncClient() as client:
        transport = Transport(client)
        with pytest.raises(FetchError, match="non-public"):
            await transport.validate("https://dmv.ca.gov/file.pdf")


async def test_dns_failure_is_explicit_and_no_request_is_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    def unresolved(*_: object) -> list[object]:
        raise socket.gaierror("resolver failed")

    visited: list[str] = []
    monkeypatch.setattr(socket, "getaddrinfo", unresolved)

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append(str(request.url))
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client)
        with pytest.raises(FetchError, match="DNS resolution failed"):
            await transport.bytes("https://dmv.ca.gov/start")
    assert visited == []


async def test_same_host_redirect_revalidates_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    resolutions: list[str] = []
    visited: list[str] = []

    def resolver(host: str, *_: object) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        resolutions.append(host)
        address = "8.8.8.8" if len(resolutions) == 1 else "127.0.0.1"
        return [(2, 1, 6, "", (address, 443))]

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append(request.url.path)
        return httpx.Response(302, headers={"Location": "/next.pdf"})

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client)
        with pytest.raises(FetchError, match="non-public"):
            await transport.bytes("https://dmv.ca.gov/start")
    assert resolutions == ["dmv.ca.gov", "dmv.ca.gov"]
    assert visited == ["/start"]


class RecordingChunks(Chunks):
    def __init__(self, parts: list[bytes]) -> None:
        super().__init__(parts)
        self.read_count = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for part in self.parts:
            self.read_count += 1
            yield part

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize("length", ["1000000", "-1", "abc", "2, 2", "9" * 5000])
async def test_bad_length_is_rejected_before_reading_and_cleans_file(
    tmp_path: Path, length: str
) -> None:
    body = RecordingChunks([b"%PDF-1.7\n" + b"x" * 30_000])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, stream=body, headers={"Content-Length": length})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client, check_dns=False)
        source = Source(
            discovery_jurisdiction="CA", url="https://dmv.ca.gov/a.pdf", discovered_via="test"
        )
        options = Options(max_pdf_bytes=50000)
        with pytest.raises(FetchError, match="Content-Length"):
            await transport.download(source, tmp_path, options)
    assert body.read_count == 0
    assert body.closed
    assert not list(tmp_path.rglob("*.pdf"))
    assert not list(tmp_path.rglob(".download-*"))


async def test_forged_small_length_cannot_mask_a_larger_stream(tmp_path: Path) -> None:
    body = RecordingChunks([b"%PDF-1.7\n", b"x" * 30_000])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, stream=body, headers={"Content-Length": "8"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client, check_dns=False)
        source = Source(
            discovery_jurisdiction="CA", url="https://dmv.ca.gov/a.pdf", discovered_via="test"
        )
        options = Options()
        with pytest.raises(FetchError, match="does not match"):
            await transport.download(source, tmp_path, options)
    assert body.closed
    assert not list(tmp_path.rglob("*.pdf"))
    assert not list(tmp_path.rglob(".download-*"))


@pytest.mark.parametrize("length", [None, "1"])
async def test_chunked_or_forged_stream_cannot_exceed_limit(
    tmp_path: Path, length: str | None
) -> None:
    body = RecordingChunks([b"%PDF-1.7\n", b"x" * 512, b"x" * 1024, b"not-consumed"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        headers = {"Content-Length": length} if length else {}
        return httpx.Response(200, stream=body, headers=headers)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client, check_dns=False)
        source = Source(
            discovery_jurisdiction="CA", url="https://dmv.ca.gov/a.pdf", discovered_via="test"
        )
        options = Options(max_pdf_bytes=1024)
        with pytest.raises(FetchError, match="byte limit"):
            await transport.download(source, tmp_path, options)
    assert body.read_count == 3
    assert body.closed
    assert not list(tmp_path.rglob("*.pdf"))
    assert not list(tmp_path.rglob(".download-*"))


@pytest.mark.parametrize(
    "retry_after,expected",
    [
        ("999999999999", [20.0, 20.0]),
        ("0", [0.0, 0.0]),
        ("invalid", [1.0, 2.0]),
        ("-3", [1.0, 2.0]),
    ],
)
async def test_429_retry_budget_and_delay_are_bounded(
    monkeypatch: pytest.MonkeyPatch, retry_after: str, expected: list[float]
) -> None:
    import asyncio

    delays: list[float] = []
    visited: list[str] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append(str(request.url))
        return httpx.Response(429, headers={"Retry-After": retry_after})

    monkeypatch.setattr(asyncio, "sleep", sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client, check_dns=False)
        with pytest.raises(httpx.HTTPStatusError):
            await transport.bytes("https://dmv.ca.gov/file.pdf")
    assert len(visited) == 3
    assert delays == expected


async def test_redirect_obeys_destination_origin_robots(tmp_path: Path) -> None:
    visited: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append((request.url.host, request.url.path))
        if request.url.path == "/robots.txt":
            if request.url.host == "second.gov":
                return httpx.Response(200, text="User-agent: *\nDisallow: /secret/\n")
            return httpx.Response(404)
        return httpx.Response(302, headers={"Location": "https://second.gov/secret/card.pdf"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client, check_dns=False)
        source = Source(
            discovery_jurisdiction="CA", url="https://first.gov/card.pdf", discovered_via="test"
        )
        options = Options()
        with pytest.raises(FetchError, match="robots"):
            await transport.download(source, tmp_path, options)
    assert visited == [
        ("first.gov", "/robots.txt"),
        ("first.gov", "/card.pdf"),
        ("second.gov", "/robots.txt"),
    ]
    assert not list(tmp_path.rglob(".download-*"))


@pytest.mark.parametrize("status,expected", [(401, False), (403, False), (404, True), (410, True)])
async def test_robots_status_rules_are_per_origin(status: int, expected: bool) -> None:
    visited: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append(request.url.host)
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client, check_dns=False)
        assert await transport.allowed("https://first.gov/a.pdf") is expected
        assert await transport.allowed("https://first.gov/b.pdf") is expected
        assert await transport.allowed("https://second.gov/a.pdf") is expected
    assert visited == ["first.gov", "second.gov"]


async def test_redirect_limit_closes_each_response() -> None:
    bodies: list[RecordingChunks] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = RecordingChunks([])
        bodies.append(body)
        return httpx.Response(302, stream=body, headers={"Location": f"/hop-{len(bodies)}"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client, check_dns=False)
        with pytest.raises(FetchError, match="Redirect limit"):
            await transport.bytes("https://dmv.ca.gov/start")
    assert len(bodies) == 6
    assert all(body.closed for body in bodies)


@pytest.mark.parametrize("hosts,expected_peak", [(1, 2), (20, 15)])
async def test_simultaneous_request_limits_are_enforced(hosts: int, expected_peak: int) -> None:
    import asyncio

    release = asyncio.Event()
    reached_limit = asyncio.Event()
    active = 0
    peak = 0
    by_host: dict[str, int] = {}
    host_peak: dict[str, int] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(active, peak)
        host = request.url.host
        by_host[host] = by_host.get(host, 0) + 1
        host_peak[host] = max(host_peak.get(host, 0), by_host[host])
        if active == expected_peak:
            reached_limit.set()
        try:
            await release.wait()
            return httpx.Response(200, content=b"bounded response")
        finally:
            active -= 1
            by_host[host] -= 1

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client, check_dns=False)
        tasks = [
            asyncio.create_task(transport.bytes(f"https://agency{i % hosts}.gov/{i}"))
            for i in range(40)
        ]
        try:
            await asyncio.wait_for(reached_limit.wait(), timeout=2)
            assert peak == expected_peak
            assert max(host_peak.values()) <= 2
        finally:
            release.set()
            await asyncio.gather(*tasks)
    assert active == 0


async def test_cancellation_closes_stream_and_removes_partial_file(tmp_path: Path) -> None:
    import asyncio

    waiting = asyncio.Event()
    hold = asyncio.Event()

    class WaitingChunks(RecordingChunks):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"%PDF-1.7\n" + b"x" * 25_000
            waiting.set()
            await hold.wait()
            yield b"trailing"

    body = WaitingChunks([])

    def handler(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(404)
            if request.url.path == "/robots.txt"
            else httpx.Response(200, stream=body)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        task = asyncio.create_task(
            Transport(client, check_dns=False).download(
                Source(
                    discovery_jurisdiction="CA",
                    url="https://dmv.ca.gov/a.pdf",
                    discovered_via="test",
                ),
                tmp_path,
                Options(),
            )
        )
        await asyncio.wait_for(waiting.wait(), timeout=2)
        assert list(tmp_path.rglob(".download-*"))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert body.closed
    assert not list(tmp_path.rglob(".download-*"))
    assert not list(tmp_path.rglob("*.pdf"))


async def test_deadline_cleans_partial_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    original_timeout = asyncio.timeout
    monkeypatch.setattr(asyncio, "timeout", lambda _: original_timeout(0.02))
    hold = asyncio.Event()

    class StalledChunks(RecordingChunks):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"%PDF-1.7\n"
            await hold.wait()
            yield b"never-reached"

    body = StalledChunks([])

    def handler(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(404)
            if request.url.path == "/robots.txt"
            else httpx.Response(200, stream=body)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client, check_dns=False)
        source = Source(
            discovery_jurisdiction="CA", url="https://dmv.ca.gov/a.pdf", discovered_via="test"
        )
        options = Options()
        with pytest.raises(TimeoutError):
            await transport.download(source, tmp_path, options)
    assert body.closed
    assert not list(tmp_path.rglob(".download-*"))
    assert not list(tmp_path.rglob("*.pdf"))


async def test_invalid_prefix_rejects_before_consuming_remaining_chunks(tmp_path: Path) -> None:
    body = RecordingChunks([b"<html>" * 300, b"remaining-body-that-must-not-be-consumed"])

    def handler(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(404)
            if request.url.path == "/robots.txt"
            else httpx.Response(200, stream=body)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(client, check_dns=False)
        source = Source(
            discovery_jurisdiction="CA", url="https://dmv.ca.gov/a.pdf", discovered_via="test"
        )
        options = Options()
        with pytest.raises(FetchError, match="PDF signature"):
            await transport.download(source, tmp_path, options)
    assert body.read_count == 1
    assert body.closed
    assert not list(tmp_path.rglob(".download-*"))


async def test_pdf_signature_at_last_legal_prefix_position_is_accepted(tmp_path: Path) -> None:
    payload = b"x" * 1019 + b"%PDF-" + b"x" * 25_000

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            stream=Chunks([payload[:1021], payload[1021:1023], payload[1023:]]),
            headers={"Content-Length": str(len(payload))},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await Transport(client, check_dns=False).download(
            Source(
                discovery_jurisdiction="CA", url="https://dmv.ca.gov/a.pdf", discovered_via="test"
            ),
            tmp_path,
            Options(),
        )
    assert (tmp_path / result.path).read_bytes() == payload
