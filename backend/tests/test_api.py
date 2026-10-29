import asyncio
import json

import httpx
import pytest

from conftest import FakeLLM, FakeTavily

from app.main import create_app
from app.memory import Memory

PLAN = {"sub_questions": [{"id": "a", "text": "What is X?"}]}
SOURCES = {"What is X?": [{"url": "https://a.com/1", "title": "A", "content": "c"}]}
DRAFT = {"claims": [{"text": "X is true", "citation_urls": ["https://a.com/1"]}]}
VER = {"verdict": "supported", "reason": "evidence"}
NARR = {"narrative": "X is true", "open_questions": ["q?"]}


def make_app(tmp_path, llm, tavily):
    memory = Memory(str(tmp_path / "t.db"))
    app = create_app(llm=llm, tavily=tavily, memory=memory)
    return app, memory


def parse_sse(raw: str) -> list[dict]:
    return [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]


async def test_profile_round_trip(tmp_path):
    app, _ = make_app(tmp_path, FakeLLM(), FakeTavily())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/profile")
        assert r.status_code == 200
        assert r.json()["persona"] == "engineer"
        r = await c.post("/api/profile", json={
            "persona": "founder", "trusted_sources": ["a.com"], "excluded_sources": ["b.com"]})
        assert r.status_code == 200
        r = await c.get("/api/profile")
        assert r.json()["persona"] == "founder"


async def test_research_sse_report_feedback_telemetry(tmp_path):
    llm = FakeLLM([PLAN, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    app, memory = make_app(tmp_path, llm, FakeTavily(SOURCES))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/research", json={"brief": "Explain X", "topic": "Explain X"})
        assert r.status_code == 200
        run_id = r.json()["run_id"]

        raw = (await c.get(f"/api/runs/{run_id}/events")).text
        events = parse_sse(raw)
        stages = [e["stage"] for e in events if e["stage"] != "__end__"]
        assert stages == ["planning", "searching", "drafting", "verifying", "synthesizing", "done"]

        r = await c.get(f"/api/report/{run_id}")
        assert r.status_code == 200
        assert r.json()["brief"] == "Explain X"
        assert memory.get_report(run_id)["brief"] == "Explain X"

        r = await c.post("/api/feedback", json={"run_id": run_id, "claim_id": "c1", "helpful": False})
        assert r.status_code == 200
        assert memory.feedback_count() == 1

        r = await c.get("/api/telemetry")
        assert r.status_code == 200
        assert "tf_calls" in r.json()


async def test_sse_late_subscriber_gets_replay(tmp_path):
    llm = FakeLLM([PLAN, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    app, _ = make_app(tmp_path, llm, FakeTavily(SOURCES))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        run_id = (await c.post("/api/research", json={"brief": "Explain X"})).json()["run_id"]
        # force run completion BEFORE subscribing: late subscriber is the normal fast-fail path
        for task in list(app.state.background_tasks):
            await task
        raw = await asyncio.wait_for(c.get(f"/api/runs/{run_id}/events"), timeout=5)  # must terminate
        events = parse_sse(raw.text)
        assert events[-1]["stage"] == "done"


async def test_background_task_registered(tmp_path):
    llm = FakeLLM([PLAN, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    app, _ = make_app(tmp_path, llm, FakeTavily(SOURCES))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/research", json={"brief": "Explain X"})
        assert len(app.state.background_tasks) >= 1


def _sentinel_loop(seen):
    async def loop(state, interval_minutes=30):
        try:
            while True:
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            seen["cancelled"] = True
            raise
    return loop


def test_shutdown_awaits_watch_task(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.watcher as W
    seen = {"cancelled": False}
    monkeypatch.setattr(W, "watch_loop", _sentinel_loop(seen))
    app = create_app(llm=FakeLLM(), tavily=FakeTavily(), memory=Memory(str(tmp_path / "t.db")),
                     watch_interval_minutes=1)
    with TestClient(app):
        pass
    assert seen["cancelled"] is True  # cancellation observed, not just requested
    assert app.state.watch_task.cancelled() is True  # awaited to completion before shutdown


def test_digest_webhook_url_injected(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.watcher as W
    captured = {}

    async def spy_loop(state, interval_minutes=30):
        captured["webhook_url"] = state.get("webhook_url")
        while True:
            await asyncio.sleep(0.05)

    monkeypatch.setattr(W, "watch_loop", spy_loop)
    app = create_app(llm=FakeLLM(), tavily=FakeTavily(), memory=Memory(str(tmp_path / "t.db")),
                     watch_interval_minutes=1, digest_webhook_url="http://x.local/hook")
    with TestClient(app):
        pass
    assert captured["webhook_url"] == "http://x.local/hook"


async def test_post_note_returns_warnings_and_saves(tmp_path):
    app, memory = make_app(tmp_path, FakeLLM(), FakeTavily())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/notes", json={"topic": "Explain X",
                                             "content": "my key is sk-abcdef12345678 keep private"})
        assert r.status_code == 200
        assert r.json()["warnings"]  # secret pattern flagged loudly at save-time
        r = await c.get("/api/notes", params={"topic": "Explain X"})
        assert any("sk-abcdef12345678" in n["content"] for n in r.json())  # warn-and-save, never silent


async def test_purge_endpoint_wipes_everything(tmp_path):
    llm = FakeLLM([PLAN, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    app, memory = make_app(tmp_path, llm, FakeTavily(SOURCES))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/research", json={"brief": "Explain X", "topic": "Explain X"})
        for task in list(app.state.background_tasks):
            await task
        await c.post("/api/notes", json={"topic": "Explain X", "content": "private note"})
        await c.post("/api/profile", json={"persona": "founder"})

        r = await c.delete("/api/memory")
        assert r.status_code == 200

        r = await c.get("/api/memory")
        assert r.json()["runs"] == []
        r = await c.get("/api/profile")
        assert r.json()["persona"] == "engineer"  # back to defaults — profile wiped
        r = await c.get("/api/notes", params={"topic": "Explain X"})
        assert r.json() == []


async def test_error_run_reports_failed_stage(tmp_path):
    llm = FakeLLM([PLAN, ValueError("boom")], planner_model="m-p", verifier_models=["m-v"])
    app, _ = make_app(tmp_path, llm, FakeTavily(SOURCES))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        run_id = (await c.post("/api/research", json={"brief": "Explain X"})).json()["run_id"]
        events = parse_sse((await c.get(f"/api/runs/{run_id}/events")).text)
        err = [e for e in events if e["stage"] == "error"][0]
        assert err["payload"]["failed_stage"] == "drafting"


async def test_budget_guard_429(tmp_path, monkeypatch):
    llm = FakeLLM([PLAN, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    memory = Memory(str(tmp_path / "t.db"))
    from app.main import create_app as ca
    app = ca(llm=llm, tavily=FakeTavily(SOURCES), memory=memory, daily_token_budget=1000)
    from app.telemetry import telemetry
    telemetry.add(tf_tokens=5000)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/research", json={"brief": "Explain X"})
        assert r.status_code == 429
        assert "budget" in r.json()["error"].lower()


async def test_watch_edit_endpoint(tmp_path):
    app, memory = make_app(tmp_path, FakeLLM(), FakeTavily())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        wid = (await c.post("/api/watch", json={"topic": "t", "brief": "b", "persona": "founder",
                                                "interval_hours": 6})).json()["id"]
        r = await c.put(f"/api/watch/{wid}", json={"brief": "new brief", "interval_hours": 12})
        assert r.status_code == 200
        w = (await c.get("/api/watch")).json()[0]
        assert w["brief"] == "new brief" and w["interval_hours"] == 12
        r = await c.put("/api/watch/999", json={"brief": "x"})
        assert r.status_code == 404
        r = await c.put(f"/api/watch/{wid}", json={})
        assert r.status_code == 200  # empty update = no-op, not error


async def test_provenance_not_spoofable(tmp_path):
    llm = FakeLLM([PLAN, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    app, memory = make_app(tmp_path, llm, FakeTavily(SOURCES))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/research", json={"brief": "Explain X", "source": "watch"})
        for task in list(app.state.background_tasks):
            await task
        assert memory.list_runs()[0]["source"] == "manual"  # client cannot forge provenance


async def test_watch_cap_429(tmp_path):
    memory = Memory(str(tmp_path / "t.db"))
    from app.main import create_app as ca
    app = ca(llm=FakeLLM(), tavily=FakeTavily(), memory=memory, max_watches=2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.post("/api/watch", json={"topic": "t1", "brief": "b1"})).status_code == 200
        assert (await c.post("/api/watch", json={"topic": "t2", "brief": "b2"})).status_code == 200
        r = await c.post("/api/watch", json={"topic": "t3", "brief": "b3"})
        assert r.status_code == 429
        assert "watch limit" in r.json()["error"].lower()
        assert len(memory.list_watches()) == 2


async def test_skill_run_watch_skipped_at_cap(tmp_path):
    memory = Memory(str(tmp_path / "t.db"))
    memory.add_watch("existing", "b", "founder")
    from app.main import create_app as ca
    llm = FakeLLM([PLAN, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    app = ca(llm=llm, tavily=FakeTavily(SOURCES), memory=memory, max_watches=1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/skills", json={"name": "s", "persona": "analyst", "brief_template": "Explain X",
                                          "topic": "Explain X"})
        r = await c.post("/api/skills/s/run", json={"watch": True})
        assert r.status_code == 200
        body = r.json()
        assert body.get("run_id")  # run still starts
        assert "watch limit" in body.get("watch_skipped", "").lower()
        for task in list(app.state.background_tasks):
            await task
        assert len(memory.list_watches()) == 1  # no new watch row
