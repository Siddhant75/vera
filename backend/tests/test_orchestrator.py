import pytest

from conftest import FakeLLM, FakeTavily

from app.memory import Memory
from app.pipeline.orchestrator import run_research

PLAN = {"sub_questions": [{"id": "a", "text": "What is X?"}]}
SOURCES = {"What is X?": [{"url": "https://a.com/1", "title": "A", "content": "c"}]}
DRAFT = {"claims": [{"text": "X is true", "citation_urls": ["https://a.com/1"]}]}
VERDICT_SUP = {"verdict": "supported", "reason": "evidence"}
NARR = {"narrative": "X is true [supported]", "open_questions": ["q2?"]}


def stages(events):
    return [e["stage"] for e in events if e["stage"] != "__end__"]


def make_llm(responses):
    return FakeLLM(responses, planner_model="m-planner", verifier_models=["m-ver"])


def make_tavily():
    return FakeTavily(SOURCES)


async def test_happy_path_order_and_persistence(tmp_path):
    llm = make_llm([PLAN, DRAFT, VERDICT_SUP, VERDICT_SUP, NARR])
    memory = Memory(str(tmp_path / "t.db"))
    events = []

    async def emit(e):
        events.append(e)

    report = await run_research("r1", "Explain X", "engineer", "", False,
                                llm, make_tavily(), memory, emit)
    assert stages(events) == ["planning", "searching", "drafting", "verifying", "synthesizing", "done"], events
    done = [e for e in events if e["stage"] == "done"][0]
    assert done["payload"]["report"] == report.model_dump()
    assert memory.last_report_for_topic("explain-x") == report.model_dump()


async def test_llm_error_emits_error_event(tmp_path):
    llm = make_llm([PLAN, ValueError("drafter blew up")])
    tavily = FakeTavily(SOURCES)
    memory = Memory(str(tmp_path / "t.db"))
    events = []

    async def emit(e):
        events.append(e)

    await run_research("r1", "Explain X", "engineer", "", False, llm, tavily, memory, emit)
    assert stages(events)[-1] == "error"
    assert [e for e in events if e["stage"] != "__end__"][-1]["payload"]["failed_stage"] == "drafting"
    assert "drafter blew up" in [e for e in events if e["stage"] != "__end__"][-1]["payload"]["detail"]
    assert stages(events)[:2] == ["planning", "searching"]


async def test_delta_without_prior_falls_back_full(tmp_path):
    llm = make_llm([PLAN, DRAFT, VERDICT_SUP, VERDICT_SUP, NARR])
    tavily = FakeTavily(SOURCES)
    memory = Memory(str(tmp_path / "t.db"))
    events = []

    async def emit(e):
        events.append(e)

    report = await run_research("r1", "Explain X", "engineer", "", True, llm, tavily, memory, emit)
    assert report.changes == []
    assert "previous" not in str(llm.prompts[0]).lower()


async def test_delta_with_prior_in_prompt_and_changes(tmp_path):
    prior = {"sections": [{"sub_question": "What is X?", "narrative": "old", "claims": []}],
             "open_questions": ["prior q?"]}
    llm = make_llm([PLAN, DRAFT, VERDICT_SUP, VERDICT_SUP, {"changes": ["now supported"]}, NARR])
    tavily = FakeTavily(SOURCES)
    memory = Memory(str(tmp_path / "t.db"))
    memory.save_run("old brief", "engineer", "explain-x", prior)
    events = []

    async def emit(e):
        events.append(e)

    report = await run_research("r1", "Explain X again", "engineer", "Explain X", True,
                                llm, tavily, memory, emit)
    assert report.changes == ["now supported"]
    assert "prior q?" in str(llm.prompts[0])
    assert report.topic_key == "explain-x"


async def test_topic_param_controls_key():
    from app.pipeline.orchestrator import resolve_topic_key
    assert resolve_topic_key("", "Brief text here") == "brief-text-here"
    assert resolve_topic_key("My Topic", "Brief text here") == "my-topic"
