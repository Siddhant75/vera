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
DRAFT = {"claims": [{"text": "X is fast", "citation_urls": ["https://nvidia.com/x"]}]}
VERDICT_SUP = {
    "verdict": "supported",
    "reason": "verified on nvidia.com",
    "votes": [{"model": "m-v", "verdict": "supported", "reason": "ok"}],
    "prosecution": "",
    "web_checked": False,
}
NARR = {"narrative": "X is fast.", "open_questions": []}


@pytest.mark.anyio
async def test_run_summary_persisted_in_report(tmp_path):
    mem = Memory(str(tmp_path / "test.db"))
    llm = FakeLLM([PLAN, DRAFT, VERDICT_SUP, VERDICT_SUP, NARR], planner_model="m-p", verifier_models=["m-v1", "m-v2"])
    tavily = FakeTavily()
    events = []

    async def emit(e):
        events.append(e)

    report = await run_research("run-123", "test brief", "engineer", "test", False, llm, tavily, mem, emit)

    # 1. report model must contain run_summary with complete metrics
    assert hasattr(report, "run_summary")
    assert isinstance(report.run_summary, dict)
    assert "tf_tokens_run" in report.run_summary
    assert "tf_calls_run" in report.run_summary
    assert "tavily_searches_run" in report.run_summary
    assert "tavily_grounding" in report.run_summary
    assert "claims_verified" in report.run_summary

    # 2. report reloaded from SQLite memory must preserve run_summary
    stored = mem.get_report("run-123")
    assert stored is not None
    assert "run_summary" in stored
    assert stored["run_summary"]["tf_tokens_run"] == report.run_summary["tf_tokens_run"]
    assert stored["run_summary"]["tf_calls_run"] == report.run_summary["tf_calls_run"]
