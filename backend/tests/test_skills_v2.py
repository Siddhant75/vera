import pytest

from conftest import FakeLLM, FakeTavily

from app.memory import Memory
from app.main import create_app

PLAN = {"sub_questions": [{"id": "a", "text": "What is X?"}]}
DRAFT = {"claims": [{"text": "X", "citation_urls": ["https://a.com/1"]}]}
VER = {"verdict": "supported", "reason": "r"}
NARR = {"narrative": "n", "open_questions": []}


def _memory(tmp_path):
    return Memory(str(tmp_path / "t.db"))


def test_template_vars_filled():
    from app.skills import fill_template
    filled = fill_template("Compare {topic} for {quarter} given {team_size}",
                           {"topic": "k8s vs serverless", "team_size": "8"},
                           {"date": "2026-10-29", "quarter": "Q4-2026"})
    assert filled == "Compare k8s vs serverless for Q4-2026 given 8"


def test_unknown_var_left_literal():
    from app.skills import fill_template
    assert fill_template("research {nope} now", {}, {}) == "research {nope} now"


def test_topic_date_quarter_auto():
    from app.skills import fill_template
    filled = fill_template("watch {topic} in {quarter} on {date}", {},
                           {"topic": "agents", "date": "2026-10-29", "quarter": "Q4-2026"})
    assert filled == "watch agents in Q4-2026 on 2026-10-29"


async def test_skill_run_fills_template_and_creates_watch(tmp_path):
    m = _memory(tmp_path)
    m.upsert_skill("infra-watch", "founder", "Deep dive {topic} for {quarter}", "k8s choice")
    llm = FakeLLM([PLAN, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])

    class App:  # minimal create_app harness via real factory instead
        pass

    app = create_app(llm=llm, tavily=FakeTavily({"Deep dive k8s choice for Q4-2026": [
        {"url": "https://a.com/1", "title": "A", "content": "c"}]}), memory=m)
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/skills/infra-watch/run", json={
            "vars": {"topic": "k8s choice"}, "watch": True})
        assert r.status_code == 200
        run_id = r.json()["run_id"]
        assert r.json()["watch_id"] >= 1
        for t in list(app.state.background_tasks):
            await t  # pipeline is a background task — let it finish
        assert "k8s choice for Q4-2026" in str(llm.prompts[0])  # filled brief reached planner
        assert m.get_report(run_id) is not None
    watches = m.list_watches()
    assert len(watches) == 1
    assert "k8s choice for Q4-2026" in watches[0]["brief"]


async def test_skill_run_missing_skill_404(tmp_path):
    m = _memory(tmp_path)
    app = create_app(llm=FakeLLM(), tavily=FakeTavily(), memory=m)
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/skills/ghost/run", json={})
        assert r.status_code == 404


async def test_skill_run_preserves_profile_context(tmp_path):
    m = _memory(tmp_path)
    m.set_profile("founder", [], [], role_context="CTO of 10-person startup",
                  goals="ship ML API", expertise_notes="knows Docker")
    m.upsert_skill("s", "analyst", "brief text", "topic t")
    llm = FakeLLM([PLAN, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    app = create_app(llm=llm, tavily=FakeTavily({"brief text": [
        {"url": "https://a.com/1", "title": "A", "content": "c"}]}), memory=m)
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/skills/s/run", json={})
        p = m.get_profile()
        assert p["role_context"] == "CTO of 10-person startup"  # context survives skill run
        assert p["persona"] == "founder"  # FLIPPED: skill runs never mutate the stored profile


async def test_skill_run_uses_skill_sources_without_profile_mutation(tmp_path):
    m = _memory(tmp_path)
    m.set_profile("founder", [], [])
    m.upsert_skill("s", "analyst", "brief text", "topic t",
                   trusted=["skill-src.com"], excluded=["spam.io"])
    llm = FakeLLM([PLAN, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    tavily = FakeTavily({"brief text": [{"url": "https://a.com/1", "title": "A", "content": "c"}]})
    app = create_app(llm=llm, tavily=tavily, memory=m)
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/skills/s/run", json={})
        for t in list(app.state.background_tasks):
            await t
    assert m.get_profile()["trusted_sources"] == []  # stored profile untouched
    assert any(kw.get("include_domains") == ["skill-src.com"] for kw in tavily.kwargs)
    assert any(kw.get("exclude_domains") == ["spam.io"] for kw in tavily.kwargs)


async def test_skill_run_budget_429_not_500(tmp_path):
    m = _memory(tmp_path)
    m.upsert_skill("s", "founder", "brief", "t")
    from app import telemetry
    telemetry.telemetry.add(tf_tokens=10_000_000)
    app = create_app(llm=FakeLLM(), tavily=FakeTavily(), memory=m, daily_token_budget=1000)
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/skills/s/run", json={})
        assert r.status_code == 429  # was 500: dict(JSONResponse) crashed


async def test_drafter_receives_notes(tmp_path):
    m = _memory(tmp_path)
    m.add_note("explain-x", "SECRET internal SLA is 45 minutes for the p99 inference latency budget")
    llm = FakeLLM([PLAN, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    from app.pipeline.orchestrator import run_research

    async def noop(e):
        pass

    await run_research("n2", "Explain X", "engineer", "", False, llm,
                       FakeTavily({"What is X?": [{"url": "https://a.com/1", "title": "A", "content": "c"}]}),
                       memory=m, emit=noop)
    assert "SECRET" in str(llm.prompts[1])  # drafter prompt carries notes too
