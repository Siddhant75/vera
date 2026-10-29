import httpx
import pytest

from app import telemetry
from app.search import SearchError, TavilyClient

TAVILY_BODY = {
    "results": [
        {"url": "https://x.com/a", "title": "A", "content": "ca", "score": 0.9},
        {"url": "https://y.org/b", "title": "B", "content": "cb"},
    ]
}


def _client(handler) -> TavilyClient:
    return TavilyClient("tkey", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_search_maps_results():
    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            body = json_loads = request.read()
            assert b"my query" in body
            return httpx.Response(200, json=TAVILY_BODY)

        c = _client(handler)
        out = await c.search("my query", max_results=5)
        await c._http.aclose()
        return out

    out = await _run()
    assert out == [
        {"url": "https://x.com/a", "title": "A", "content": "ca"},
        {"url": "https://y.org/b", "title": "B", "content": "cb"},
    ]


@pytest.mark.asyncio
async def test_search_empty_results():
    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": []})

        c = _client(handler)
        out = await c.search("q")
        await c._http.aclose()
        return out

    assert await _run() == []


@pytest.mark.asyncio
async def test_search_401_raises():
    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="unauthorized")

        c = _client(handler)
        try:
            await c.search("q")
        finally:
            await c._http.aclose()

    with pytest.raises(SearchError):
        await _run()


@pytest.mark.asyncio
async def test_search_counts_telemetry():
    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=TAVILY_BODY)

        c = _client(handler)
        await c.search("q")
        await c._http.aclose()

    await _run()
    assert telemetry.telemetry.snapshot()["tavily_queries"] == 1


@pytest.mark.asyncio
async def test_search_domain_prefs_in_body():
    captured = {}

    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json
            captured["body"] = _json.loads(request.read())
            return httpx.Response(200, json=TAVILY_BODY)

        c = _client(handler)
        await c.search("q", include_domains=["trusted.com"], exclude_domains=["banned.com"])
        await c._http.aclose()

    await _run()
    body = captured["body"]
    assert body["include_domains"] == ["trusted.com"]
    assert body["include_domains_mode"] == "prefer"
    assert body["exclude_domains"] == ["banned.com"]


@pytest.mark.asyncio
async def test_search_no_include_no_mode_key():
    captured = {}

    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json
            captured["body"] = _json.loads(request.read())
            return httpx.Response(200, json=TAVILY_BODY)

        c = _client(handler)
        await c.search("q", exclude_domains=["banned.com"])
        await c._http.aclose()

    await _run()
    body = captured["body"]
    assert body["exclude_domains"] == ["banned.com"]
    assert "include_domains" not in body
    assert "include_domains_mode" not in body  # Tavily 400s on mode without include


@pytest.mark.asyncio
async def test_search_topic_and_time_range():
    captured = {}

    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json
            captured["body"] = _json.loads(request.read())
            return httpx.Response(200, json=TAVILY_BODY)

        c = _client(handler)
        await c.search("q", topic="news", time_range="week")
        await c._http.aclose()

    await _run()
    assert captured["body"]["topic"] == "news"
    assert captured["body"]["time_range"] == "week"


@pytest.mark.asyncio
async def test_search_probe_role_telemetry():
    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=TAVILY_BODY)

        c = _client(handler)
        await c.search("q", role="probe")
        await c._http.aclose()

    await _run()
    snap = telemetry.telemetry.snapshot()
    assert snap["tavily_probe"] == 1
    assert snap["tavily_queries"] == 1


@pytest.mark.asyncio
async def test_extract_maps_results():
    captured = {}

    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json
            captured["body"] = _json.loads(request.read())
            return httpx.Response(200, json={
                "results": [
                    {"url": "https://a.com/1", "raw_content": "full page text"},
                    {"url": "https://b.com/2", "raw_content": "second page"},
                ],
                "failed_results": [{"url": "https://dead.com/x"}],
            })

        c = _client(handler)
        out = await c.extract(["https://a.com/1", "https://b.com/2", "https://dead.com/x"], query="claim text")
        await c._http.aclose()
        return out

    out = await _run()
    assert out == [
        {"url": "https://a.com/1", "content": "full page text"},
        {"url": "https://b.com/2", "content": "second page"},
    ]  # failed_results skipped
    assert captured["body"]["urls"] == ["https://a.com/1", "https://b.com/2", "https://dead.com/x"]
    assert captured["body"]["query"] == "claim text"
    assert captured["body"]["extract_depth"] == "basic"


@pytest.mark.asyncio
async def test_extract_500_raises():
    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        c = _client(handler)
        try:
            await c.extract(["https://a.com/1"])
        finally:
            await c._http.aclose()

    with pytest.raises(SearchError):
        await _run()
