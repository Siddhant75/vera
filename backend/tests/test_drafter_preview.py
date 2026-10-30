import pytest
from app.memory import Memory
from app.pipeline.orchestrator import run_research
from tests.conftest import FakeLLM, FakeTavily

PLAN = {
    "brief": "test brief",
    "persona": "engineer",
    "topic_key": "test",
    "depth": "quick",
    "sub_questions": [{"id": "q1", "text": "What is X?"}],
    "coverage": [{"requirement": "test brief", "sq_ids": ["q1"]}],
}
SOURCES = {"What is X?": [{"url": "https://nvidia.com/x", "title": "X", "content": "fast"}]}
DRAFT = {"claims": [{"text": "X is fast", "citation_urls": ["https://nvidia.com/x"]}]}
VERDICT_SUP = {
    "verdict": "supported",
    "reason": "ok",
    "votes": [],
    "prosecution": "",
    "web_checked": False,
}
NARR = {"narrative": "X is fast.", "open_questions": []}


@pytest.mark.anyio
async def test_verifying_stage_carries_draft_claims_preview(tmp_path):
    mem = Memory(str(tmp_path / "test.db"))
    llm = FakeLLM([PLAN, DRAFT, VERDICT_SUP, VERDICT_SUP, NARR], planner_model="m-p", verifier_models=["m-v"])
    tavily = FakeTavily(SOURCES)
    events = []

    async def emit(e):
        events.append(e)

    await run_research("run-125", "test brief", "engineer", "test", False, llm, tavily, mem, emit)

    verifying_events = [e for e in events if e.get("stage") == "verifying"]
    assert len(verifying_events) == 1
    payload = verifying_events[0]["payload"]
    assert "draft_claims" in payload
    assert len(payload["draft_claims"]) == 1
    assert payload["draft_claims"][0]["text"] == "X is fast"
    assert payload["draft_claims"][0]["citations"] == ["https://nvidia.com/x"]
    # Verify stages order is strictly preserved
    stage_names = [e["stage"] for e in events if e.get("stage") != "__end__"]
    assert stage_names == ["planning", "searching", "drafting", "verifying", "synthesizing", "done"]
