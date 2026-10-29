import httpx
import pytest

from conftest import FakeLLM, FakeTavily

from app.memory import Memory
from app.watcher import _post_digest, check_due_watches


class RecordingTavily(FakeTavily):
    """Tavily double whose probe always says: nothing new (no LLM run needed) —
    webhook tests exercise the no-change path, plus a changed variant below."""
    pass


def _capture_post(captured):
    def handler(request: httpx.Request) -> httpx.Response:
        import json
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json={"ok": True})
    return handler


def _memory_with_watch(tmp_path, status_seed=None):
    m = Memory(str(tmp_path / "t.db"))
    m.add_watch("Explain X", "Explain X", "engineer")
    return m


@pytest.mark.asyncio
async def test_digest_posted_on_change(tmp_path, monkeypatch):
    from app import telemetry
    telemetry.telemetry.reset()
    m = _memory_with_watch(tmp_path)
    PLAN = {"sub_questions": [{"id": "a", "text": "What is X?"}]}
    DRAFT = {"claims": [{"text": "X changed", "citation_urls": ["https://a.com/1"]}]}
    VER = {"verdict": "supported", "reason": "r"}
    NARR = {"narrative": "n", "open_questions": []}
    llm = FakeLLM([PLAN, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    tavily = FakeTavily({"Explain X": [{"url": "https://a.com/1", "title": "A", "content": "c"}]})
    posted = []

    async def cap(text, payload, url):
        posted.append((text, payload))

    monkeypatch.setattr("app.watcher._post_digest", cap)

    async def noop(e):
        pass

    await check_due_watches(m, llm, tavily, emit=noop, probe_fn=_changed_probe,
                           webhook_url="http://hook.local/x")
    w = m.list_watches()[0]
    assert w["last_status"] == "changed"
    assert posted and "Explain X" in posted[0][0]


async def _changed_probe(memory, tavily, watch):
    return True


async def _not_changed_probe(memory, tavily, watch):
    return False


@pytest.mark.asyncio
async def test_webhook_500_does_not_break_watch(tmp_path, monkeypatch):
    m = _memory_with_watch(tmp_path)
    PLAN = {"sub_questions": [{"id": "a", "text": "What is X?"}]}
    DRAFT = {"claims": []}
    llm = FakeLLM([PLAN, DRAFT], planner_model="m-p", verifier_models=["m-v"])
    tavily = FakeTavily({"Explain X": [{"url": "https://a.com/1", "title": "A", "content": "c"}]})

    async def failing_post(text, payload, url):
        raise httpx.ConnectError("webhook down")

    monkeypatch.setattr("app.watcher._post_digest", failing_post)

    async def noop(e):
        pass

    await check_due_watches(m, llm, tavily, emit=noop, probe_fn=_changed_probe,
                           webhook_url="http://hook.local/x")
    assert m.list_watches()[0]["last_status"] == "changed"


@pytest.mark.asyncio
async def test_no_change_no_post(tmp_path, monkeypatch):
    posted = []
    m = _memory_with_watch(tmp_path)
    llm = FakeLLM()

    async def cap(text, payload, url):
        posted.append(text)

    monkeypatch.setattr("app.watcher._post_digest", cap)

    async def noop(e):
        pass

    await check_due_watches(m, llm, FakeTavily(), emit=noop, probe_fn=_not_changed_probe,
                           webhook_url="http://hook.local/x")
    assert m.list_watches()[0]["last_status"] == "no-change"
    assert posted == []


@pytest.mark.asyncio
async def test_empty_webhook_no_post(tmp_path, monkeypatch):
    posted = []
    m = _memory_with_watch(tmp_path)

    async def cap(text, payload, url):
        posted.append(text)

    monkeypatch.setattr("app.watcher._post_digest", cap)

    async def noop(e):
        pass

    await check_due_watches(m, FakeLLM(), FakeTavily(), emit=noop, probe_fn=_changed_probe,
                           webhook_url="")
    assert posted == []


@pytest.mark.asyncio
async def test_post_digest_raises_on_http_error(monkeypatch):
    real_client = httpx.AsyncClient

    def fake_client(**kw):
        return real_client(transport=httpx.MockTransport(lambda r: httpx.Response(500)), timeout=10)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    with pytest.raises(httpx.HTTPStatusError):
        await _post_digest("t", {}, "http://hook.local/x")
