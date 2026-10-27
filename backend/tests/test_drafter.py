from conftest import FakeLLM

from app.models import ResearchPlan, Source, SubQuestion
from app.pipeline.drafter import draft_claims

PLAN = ResearchPlan(
    brief="b", persona="engineer", topic_key="k",
    sub_questions=[SubQuestion(id="q1", text="What is X?"), SubQuestion(id="q2", text="Why X?")],
)

SOURCES = [
    Source(url="https://a.com/1", title="A1", content="c1", sub_question_id="q1"),
    Source(url="https://a.com/2", title="A2", content="c2", sub_question_id="q1"),
]
# q2 has no sources

DRAFT_OK = {
    "claims": [
        {"text": "X is true", "citation_urls": ["https://a.com/1"]},
        {"text": "X is big", "citation_urls": ["https://a.com/2", "https://rogue.com/z"]},
    ]
}


def profile():
    return {"persona": "engineer", "trusted_sources": [], "excluded_sources": []}


async def test_claims_parsed_ids_and_filtering():
    llm = FakeLLM([DRAFT_OK, {"claims": []}])
    out = await draft_claims("b", PLAN, SOURCES, profile(), llm, "m-draft")
    assert [c.id for c in out] == ["c1", "c2"]
    assert out[0].citation_urls == ["https://a.com/1"]
    assert out[1].citation_urls == ["https://a.com/2"]  # rogue url dropped
    assert out[0].sub_question_id == "q1"


async def test_zero_source_subquestion_skips_llm():
    llm = FakeLLM([DRAFT_OK])
    out = await draft_claims("b", PLAN, SOURCES, profile(), llm, "m-draft")
    assert len(llm.prompts) == 1  # q2 never drafted
    assert all(c.sub_question_id == "q1" for c in out)


async def test_fully_uncited_claim_dropped():
    llm = FakeLLM([{"claims": [{"text": "no cites", "citation_urls": []}]}, {"claims": []}])
    out = await draft_claims("b", PLAN, SOURCES, profile(), llm, "m-draft")
    assert out == []
