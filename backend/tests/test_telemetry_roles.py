import httpx
import pytest

from app import telemetry
from app.search import TavilyClient

BODY = {"results": [{"url": "https://x.com/a", "title": "A", "content": "c"}]}


def _client():
    return TavilyClient("tkey", http=httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=BODY))))


@pytest.mark.asyncio
async def test_role_counted_in_split():
    c = _client()
    await c.search("q", role="prosecution")
    await c.search("q", role="recheck")
    await c.search("q")  # default grounding
    snap = telemetry.telemetry.snapshot()
    assert snap["tavily_prosecution"] == 1
    assert snap["tavily_recheck"] == 1
    assert snap["tavily_grounding"] == 1
    assert snap["tavily_queries"] == 3  # total kept


@pytest.mark.asyncio
async def test_unknown_role_raises():
    c = _client()
    with pytest.raises(ValueError, match="role"):
        await c.search("q", role="vibes")
