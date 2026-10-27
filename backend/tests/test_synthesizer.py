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
