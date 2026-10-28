import pytest

from conftest import FakeLLM, FakeTavily

from app.memory import Memory
from app.pipeline.orchestrator import run_research


def test_note_round_trip_truncation_eviction(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    nid, warnings = m.add_note("k", "hello" * 3000)  # 15k chars
    assert nid > 0 and warnings == []
    stored = m.list_notes("k")
    assert len(stored) == 1 and len(stored[0]["content"]) == 10_000
    for i in range(6):
        m.add_note("k", f"note {i}")
    notes = m.list_notes("k")
    assert len(notes) == 5
    assert all("hello" not in n["content"] for n in notes)  # oldest evicted
    m.delete_note(notes[0]["id"])
    assert len(m.list_notes("k")) == 4


async def test_note_in_planner_but_not_in_queries(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.add_note("explain-x", "SECRET internal SLA is 45 minutes for the p99 inference latency budget")
    PLAN = {"sub_questions": [{"id": "a", "text": "What is X?"}]}
    DRAFT = {"claims": [{"text": "X", "citation_urls": ["https://a.com/1"]}]}
    VER = {"verdict": "supported", "reason": "r"}
    NARR = {"narrative": "n", "open_questions": []}
    llm = FakeLLM([PLAN, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    # planner is leaky: sub-question echoes the note's private phrase — gate must strip it
    leaky_plan = {"sub_questions": [{"id": "a", "text": "what is the internal SLA is 45 minutes for p99"}]}
    llm = FakeLLM([leaky_plan, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    tavily = FakeTavily({"explain-x": [{"url": "https://a.com/1", "title": "A", "content": "c"}]})
    events = []

    async def emit(e):
        events.append(e)

    report = await run_research("n1", "Explain X", "engineer", "", False, llm, tavily, memory=m, emit=emit)
    assert "SECRET" in str(llm.prompts[0])  # planner sees private notes
    queries = " || ".join(tavily.queries)
    assert "SECRET" not in queries
    for gram in ("internal SLA is", "45 minutes for"):
        assert gram not in queries  # leaky query replaced by topic-slug fallback
    assert "explain-x" in queries  # fallback query searched instead
    assert "https://a.com/1" in [c for sec in report.sections for c in sec.claims][0].citation_urls


async def test_note_topic_isolation(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.add_note("topic-x", "private note alpha bravo charlie delta echo")
    PLAN = {"sub_questions": [{"id": "a", "text": "Why Y?"}]}
    DRAFT = {"claims": []}
    llm = FakeLLM([PLAN, DRAFT], planner_model="m-p", verifier_models=["m-v"])

    async def noop(e):
        pass

    await run_research("y1", "Explain Y", "engineer", "", False, llm, FakeTavily(), memory=m, emit=noop)
    assert "alpha bravo" not in str(llm.prompts[0])  # topic-X note invisible to topic-Y run
