import json

import httpx
import pytest

from app import telemetry
from app.llm import LLMError, TokenFactoryClient

CHAT_BODY = {
    "choices": [{"message": {"content": "hello"}}],
    "usage": {"total_tokens": 42},
}


def _client(handler) -> TokenFactoryClient:
    return TokenFactoryClient(
        "https://fake/v1", "key", http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


@pytest.mark.asyncio
async def test_chat_returns_content():
    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=CHAT_BODY)

        c = _client(handler)
        out = await c.chat("m1", [{"role": "user", "content": "hi"}])
        await c._http.aclose()
        return out

    assert await _run() == "hello"


@pytest.mark.asyncio
async def test_chat_json_parses_and_counts_telemetry():
    body = dict(CHAT_BODY, choices=[{"message": {"content": json.dumps({"a": 1})}}])

    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        c = _client(handler)
        out = await c.chat_json("m1", [{"role": "user", "content": "hi"}], {"type": "object"})
        await c._http.aclose()
        return out

    assert await _run() == {"a": 1}
    snap = telemetry.telemetry.snapshot()
    assert snap["tf_calls"] == 1
    assert snap["tf_tokens"] == 42


@pytest.mark.asyncio
async def test_chat_json_retries_once_on_malformed():
    responses = ["not json", json.dumps({"ok": True})]
    seen = []

    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(1)
            return httpx.Response(200, json=dict(CHAT_BODY, choices=[{"message": {"content": responses.pop(0)}}]))

        c = _client(handler)
        out = await c.chat_json("m1", [], {"type": "object"})
        await c._http.aclose()
        return out

    assert await _run() == {"ok": True}
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_chat_json_raises_after_second_malformed():
    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=dict(CHAT_BODY, choices=[{"message": {"content": "garbage"}}]))

        c = _client(handler)
        try:
            await c.chat_json("m1", [], {"type": "object"})
        finally:
            await c._http.aclose()

    with pytest.raises(LLMError):
        await _run()


@pytest.mark.asyncio
async def test_chat_raises_on_429():
    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        c = _client(handler)
        try:
            await c.chat("m1", [])
        finally:
            await c._http.aclose()

    with pytest.raises(LLMError):
        await _run()


@pytest.mark.asyncio
async def test_list_models():
    async def _run():
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/models")
            return httpx.Response(200, json={"data": [{"id": "m/a"}, {"id": "m/b"}]})

        c = _client(handler)
        out = await c.list_models()
        await c._http.aclose()
        return out

    assert await _run() == ["m/a", "m/b"]
