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
    llm = FakeLLM([PLAN, DRAFT, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
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
    llm = FakeLLM([PLAN, DRAFT, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    app, _ = make_app(tmp_path, llm, FakeTavily(SOURCES))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        run_id = (await c.post("/api/research", json={"brief": "Explain X"})).json()["run_id"]
        # run already complete: late subscriber still sees everything
        events = parse_sse((await c.get(f"/api/runs/{run_id}/events")).text)
        assert events[-1]["stage"] == "done"


async def test_error_run_reports_failed_stage(tmp_path):
    llm = FakeLLM([PLAN, ValueError("boom")], planner_model="m-p", verifier_models=["m-v"])
    app, _ = make_app(tmp_path, llm, FakeTavily(SOURCES))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        run_id = (await c.post("/api/research", json={"brief": "Explain X"})).json()["run_id"]
        events = parse_sse((await c.get(f"/api/runs/{run_id}/events")).text)
        err = [e for e in events if e["stage"] == "error"][0]
        assert err["payload"]["failed_stage"] == "drafting"
