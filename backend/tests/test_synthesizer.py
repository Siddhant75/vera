from conftest import FakeLLM

from app.models import (
    Claim,
    ReportSection,
    ResearchPlan,
    Source,
    SubQuestion,
    Verdict,
)
from app.pipeline.synthesizer import synthesize

PLAN = ResearchPlan(
    brief="b", persona="founder", topic_key="k",
    sub_questions=[SubQuestion(id="q1", text="What is X?"), SubQuestion(id="q2", text="Why X?")],
)

CLAIM = Claim(id="c1", sub_question_id="q1", text="X is true", citation_urls=["https://a.com/1"])
SOURCE = Source(url="https://a.com/1", title="A", content="content of a", sub_question_id="q1")
VERDICTS = [Verdict(claim_id="c1", verdict="disputed", reason="split", model="mA,mB")]

NARR_OK = {"narrative": "The evidence on X is disputed", "open_questions": ["follow up"]}

PRIOR = {
    "sections": [{"sub_question": "What is X?", "narrative": "old story", "claims": []}],
    "open_questions": [],
}


async def test_report_structure_and_verdict_summary():
    llm = FakeLLM([NARR_OK, NARR_OK])  # q1, q2 both have sources? q2 none → only 1 call
    llm = FakeLLM([NARR_OK])
    report = await synthesize("b", "founder", "k", PLAN, [CLAIM], VERDICTS, [SOURCE], None, llm, "m-syn")
    assert len(report.sections) == 2
    assert report.verdict_summary == {"disputed": 1}
    assert report.claim_verdicts == {"c1": "disputed"}
    assert report.sections[0].claims == [CLAIM]
    assert "follow up" in report.open_questions


async def test_prompt_contains_persona_and_verdict_label():
    llm = FakeLLM([NARR_OK])
    await synthesize("b", "founder", "k", PLAN, [CLAIM], VERDICTS, [SOURCE], None, llm, "m-syn")
    flat = str(llm.prompts[0])
    assert "founder" in flat
    assert "disputed" in flat


async def test_prior_report_produces_changes():
    llm = FakeLLM([{"changes": ["X reversed"]}, NARR_OK])
    report = await synthesize("b", "founder", "k", PLAN, [CLAIM], VERDICTS, [SOURCE], PRIOR, llm, "m-syn")
    assert report.changes == ["X reversed"]
    assert "old story" in str(llm.prompts[0])


async def test_zero_claim_subquestion_notes_gap():
    llm = FakeLLM([])  # no LLM responses needed: q1 has no claims, q2 no sources
    plan2 = ResearchPlan(brief="b", persona="founder", topic_key="k",
                         sub_questions=[SubQuestion(id="q1", text="What is X?")])
    report = await synthesize("b", "founder", "k", plan2, [], [], [], None, llm, "m-syn")
    assert "no sources found" in report.sections[0].narrative.lower()
    assert "What is X?" in report.open_questions
    assert llm.prompts == []  # no LLM call at all


async def test_claim_proofs_surfaced():
    llm = FakeLLM([NARR_OK])
    report = await synthesize("b", "founder", "k", PLAN, [CLAIM], VERDICTS, [SOURCE], None, llm, "m-syn")
    assert report.claim_proofs == {"c1": {"verdict": "disputed", "reason": "split", "web_checked": False,
                                          "votes": [], "prosecution": ""}}


async def test_claim_proofs_include_votes_and_prosecution():
    v = Verdict(claim_id="c1", verdict="disputed", reason="split", model="mA,mB",
                votes=[{"model": "m1", "verdict": "supported", "reason": "r"}], prosecution="counter text")
    llm = FakeLLM([NARR_OK])
    report = await synthesize("b", "founder", "k", PLAN, [CLAIM], [v], [SOURCE], None, llm, "m-syn")
    proof = report.claim_proofs["c1"]
    assert proof["votes"] == [{"model": "m1", "verdict": "supported", "reason": "r"}]
    assert proof["prosecution"] == "counter text"


async def test_notes_considered_count():
    llm = FakeLLM([NARR_OK])
    report = await synthesize("b", "founder", "k", PLAN, [CLAIM], VERDICTS, [SOURCE], None, llm, "m-syn",
                              notes_count=2)
    assert report.notes_considered == 2


CITED = Claim(id="c1", sub_question_id="q1", text="X", citation_urls=["https://a.com/1"])
UNUSED_SRC = Source(url="https://unused.com/z", title="U", content="c", sub_question_id="q1")


async def test_output_caps_and_unused_sources():
    long_narr = {"narrative": "word " * 400, "open_questions": [f"q{i}" for i in range(15)]}
    llm = FakeLLM([long_narr])
    report = await synthesize("b", "founder", "k", PLAN, [CITED], [], [SOURCE, UNUSED_SRC], None, llm, "m-syn",
                              run_max_tokens=400)
    assert len(report.open_questions) <= 8
    assert report.sources_unused == [{"url": "https://unused.com/z", "title": "U"}]  # cited a.com/1 excluded
    assert llm.prompts  # section call happened


async def test_changes_capped():
    llm = FakeLLM([{"changes": [f"c{i}" for i in range(15)]}, NARR_OK])
    report = await synthesize("b", "founder", "k", PLAN, [CITED], [], [SOURCE], PRIOR, llm, "m-syn",
                              run_max_tokens=400)
    assert len(report.changes) <= 8


async def test_synthesizer_sections_parallel_preserve_order():
    import asyncio
    import time as _t

    import re as _re

    class StaggeredLLM(FakeLLM):
        async def chat_json(self, model, messages, schema, max_tokens=4096):
            self.prompts.append(messages)
            flat = str(messages)
            i = int(_re.search(r"Question (\d)\?", flat).group(1))
            await asyncio.sleep(0.15 - 0.02 * i)
            return {"narrative": f"Section {i}", "open_questions": [f"q{i}?"]}

    subs = [SubQuestion(id=f"q{i}", text=f"Question {i}?") for i in range(1, 6)]
    plan5 = PLAN.model_copy(update={"sub_questions": subs})
    claims5 = [Claim(id=f"c{i}", sub_question_id=f"q{i}", text=f"claim {i}", citation_urls=[])
               for i in range(1, 6)]
    sources5 = [Source(url=f"https://a.com/{i}", title=f"A{i}", content="c", sub_question_id=f"q{i}")
                for i in range(1, 6)]
    verd5 = [Verdict(claim_id=f"c{i}", verdict="supported", reason="r", model="m") for i in range(1, 6)]
    llm = StaggeredLLM()
    t0 = _t.monotonic()
    report = await synthesize("b", "founder", "k", plan5, claims5, verd5, sources5, None, llm, "m-s")
    elapsed = _t.monotonic() - t0
    heads = [s.sub_question for s in report.sections if s.sub_question != "Not investigated"]
    assert heads == [f"Question {i}?" for i in range(1, 6)]  # plan order
    assert [s.narrative for s in report.sections] == [f"Section {i}" for i in range(1, 6)]  # content-order match
    assert elapsed < 0.35, f"synthesizer still sequential: {elapsed:.2f}s"
