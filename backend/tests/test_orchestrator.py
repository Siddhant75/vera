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


async def test_delta_reuses_prior_subquestions(tmp_path):
    prior = {"sections": [{"sub_question": "What is X?", "narrative": "old n", "claims":
             [{"id": "c1", "text": "prior claim", "citation_urls": ["https://old.com/1"]}]}],
             "open_questions": []}
    memory = Memory(str(tmp_path / "t.db"))
    memory.save_run("old brief", "engineer", "explain-x", prior, run_uuid="old1")
    memory.save_verdicts("old1", [{"claim_id": "c1", "verdict": "supported", "reason": "ok", "model": "m"}])

    PLAN_REUSE = {"sub_questions": [
        {"id": "a", "text": "What is X?", "reuse_prior_sq": "What is X?"},
        {"id": "b", "text": "Why X?"},
    ]}
    DRAFT_Q2 = {"claims": [{"text": "because Y", "citation_urls": ["https://new.com/2"]}]}
    llm = make_llm([PLAN_REUSE, DRAFT_Q2, VERDICT_SUP, VERDICT_SUP, {"changes": ["X confirmed"]}, NARR, NARR])
    tavily = FakeTavily({"Why X?": [{"url": "https://new.com/2", "title": "N", "content": "c"}]})
    events = []

    async def emit(e):
        events.append(e)

    report = await run_research("r9", "Explain X", "engineer", "Explain X", True,
                                llm, tavily, memory, emit)
    assert [q for q in tavily.queries] == ["Why X?"]  # reused sub-question never re-searched
    reused = [c for sec in report.sections for c in sec.claims if c.id.startswith("r-")]
    assert len(reused) == 1 and reused[0].text == "prior claim"
    assert report.claim_proofs["r-c1"]["verdict"] == "supported"  # prior verdict carried over
    assert sum(len(sec.claims) for sec in report.sections) == 2  # reused + fresh


async def test_coverage_gate_retries_then_flags(tmp_path):
    from app.brief import parse_requirements
    requirements = parse_requirements("Compare k8s and serverless.\n- cold start behavior")
    assert requirements == ["cold start behavior"]
    # planner never covers the requirement → gate retries once, then flags
    llm = make_llm([PLAN, PLAN, DRAFT, VERDICT_SUP, VERDICT_SUP, NARR])
    memory = Memory(str(tmp_path / "t.db"))
    events = []

    async def emit(e):
        events.append(e)

    report = await run_research("r-cov", "Compare k8s and serverless.\n- cold start behavior",
                                "engineer", "", False, llm, make_tavily(), memory, emit)
    retry_prompt = str(llm.prompts[1])
    assert "cold start behavior" in retry_prompt  # missed requirement injected on retry
    sections_text = " ".join(s.sub_question for s in report.sections)
    assert "Not investigated" in sections_text or "not investigated" in sections_text.lower()


async def test_run_summary_and_sources_persisted(tmp_path):
    llm = make_llm([PLAN, DRAFT, VERDICT_SUP, VERDICT_SUP, NARR])
    memory = Memory(str(tmp_path / "t.db"))
    events = []

    async def emit(e):
        events.append(e)

    report = await run_research("r-sum", "Explain X", "engineer", "", False,
                                llm, make_tavily(), memory, emit)
    done = [e for e in events if e["stage"] == "done"][0]
    rs = done["payload"]["run_summary"]
    assert rs["searches_used"] == 1 and rs["search_budget"] >= 12
    assert rs["claims"] == 1 and rs["tf_tokens_run"] >= 0  # fakes bypass telemetry; real runs report
    assert "reused" in rs
    saved = memory.get_sources("r-sum")
    assert any(s["url"] == "https://a.com/1" for s in saved)
    assert report.sources_unused == []  # a.com/1 cited → nothing unused


async def test_domain_prefs_threaded_from_profile(tmp_path):
    llm = make_llm([PLAN, DRAFT, VERDICT_SUP, VERDICT_SUP, NARR])
    memory = Memory(str(tmp_path / "t.db"))
    memory.set_profile("engineer", ["a.com"], ["spam.io"])
    tavily = FakeTavily(SOURCES)
    events = []

    async def emit(e):
        events.append(e)

    await run_research("r-prefs", "Explain X", "engineer", "", False, llm, tavily, memory, emit)
    grounding = [kw for kw in tavily.kwargs if "include_domains" in kw or "exclude_domains" in kw]
    assert grounding, "grounding searches never received domain prefs"
    assert all(kw.get("include_domains") == ["a.com"] for kw in grounding)
    assert all(kw.get("exclude_domains") == ["spam.io"] for kw in grounding)


async def test_explicit_domain_prefs_win_over_profile(tmp_path):
    llm = make_llm([PLAN, DRAFT, VERDICT_SUP, VERDICT_SUP, NARR])
    memory = Memory(str(tmp_path / "t.db"))
    memory.set_profile("engineer", ["profile.com"], [])
    tavily = FakeTavily(SOURCES)
    events = []

    async def emit(e):
        events.append(e)

    await run_research("r-explicit", "Explain X", "engineer", "", False, llm, tavily, memory, emit,
                       domain_prefs={"trusted": ["explicit.com"], "excluded": []})
    grounding = [kw for kw in tavily.kwargs if "include_domains" in kw]
    assert grounding and all(kw["include_domains"] == ["explicit.com"] for kw in grounding)


async def test_run_source_persisted(tmp_path):
    llm = make_llm([PLAN, DRAFT, VERDICT_SUP, VERDICT_SUP, NARR])
    memory = Memory(str(tmp_path / "t.db"))
    events = []

    async def emit(e):
        events.append(e)

    await run_research("r-src", "Explain X", "engineer", "", False, llm, make_tavily(), memory, emit,
                       source="skill")
    row = [r for r in memory.list_runs() if r["run_uuid"] == "r-src"][0]
    assert row["source"] == "skill"


async def test_notes_considered_counted(tmp_path):
    llm = make_llm([PLAN, DRAFT, VERDICT_SUP, VERDICT_SUP, NARR])
    memory = Memory(str(tmp_path / "t.db"))
    memory.add_note("explain-x", "we already run k8s in prod")
    memory.add_note("explain-x", "budget is tight this quarter")
    events = []

    async def emit(e):
        events.append(e)

    report = await run_research("r-notes", "Explain X", "engineer", "", False,
                                llm, make_tavily(), memory, emit)
    assert report.notes_considered == 2  # count only — content never in report
    assert "k8s in prod" not in report.model_dump_json()


async def test_quick_tier_threaded_through_pipeline(tmp_path):
    PLAN_BIG = {"depth": "quick", "sub_questions": [
        {"id": "a", "text": "What is X?"}, {"id": "b", "text": "Why X?"},
        {"id": "c", "text": "When X?"}, {"id": "d", "text": "Where X?"},
        {"id": "e", "text": "Who X?"}]}
    llm = FakeLLM([PLAN_BIG, DRAFT, NARR], planner_model="m-p", verifier_models=["m-v"],
                  model_responses={"m-v": [{"refutation_query": "X is wrong", "suspicions": "s"},
                                           VERDICT_SUP, VERDICT_SUP]})
    memory = Memory(str(tmp_path / "t.db"))
    events = []

    async def emit(e):
        events.append(e)

    report = await run_research("r-quick", "Is X true?", "engineer", "", False,
                                llm, make_tavily(), memory, emit)
    done = [e for e in events if e["stage"] == "done"][0]
    assert done["payload"]["report"]["depth"] == "quick"
    assert done["payload"]["run_summary"]["search_budget"] == 8
    assert report.depth == "quick"
    assert len([s for s in report.sections if s.sub_question != "Not investigated"]) <= 3  # tier ceiling
    draft_prompt = str(llm.prompts[1])
    assert "at most 3" in draft_prompt  # claims cap per tier reached the drafter
    # quick tier: prosecutor's visible degradation lands in the report's claim proofs
    assert any("quick tier" in (pr.get("prosecution") or "").lower()
               for pr in report.claim_proofs.values())
