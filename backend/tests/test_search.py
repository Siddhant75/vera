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
