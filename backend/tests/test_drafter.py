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


async def test_long_source_content_trimmed():
    huge = "x" * 5000
    sources = [Source(url="https://a.com/1", title="A", content=huge, sub_question_id="q1")]
    llm = FakeLLM([{"claims": []}])
    await draft_claims("b", PLAN, sources, profile(), llm, "m-draft")
    assert huge not in str(llm.prompts[0])
    assert "x" * 1201 not in str(llm.prompts[0])  # each source capped ~1200 chars


async def test_claims_capped_per_subquestion():
    many = {"claims": [{"text": f"claim {i}", "citation_urls": ["https://a.com/1"]} for i in range(12)]}
    llm = FakeLLM([many])
    out = await draft_claims("b", PLAN, SOURCES, profile(), llm, "m-draft")
    assert len(out) == 5  # load-bearing claims only
    assert "at most 5" in str(llm.prompts[0])


async def test_claims_cap_per_tier():
    from app.pipeline.drafter import draft_claims
    subs = [SubQuestion(id=f"q{i}", text=f"What is X? {i}") for i in range(1, 7)]
    plan5 = PLAN.model_copy(update={"sub_questions": subs})
    sources6 = [Source(url=f"https://a.com/{i}", title=f"A{i}", content="c", sub_question_id=f"q{i}")
                for i in range(1, 7)]
    greedy = {"claims": [{"text": f"claim {i}", "citation_urls": ["https://a.com/1"]} for i in range(6)]}
    llm = FakeLLM([greedy] * 6)
    out = await draft_claims("b", plan5, sources6, {}, llm, "m-d", claims_cap=3)
    per_q = {}
    for c in out:
        per_q[c.sub_question_id] = per_q.get(c.sub_question_id, 0) + 1
    assert all(n <= 3 for n in per_q.values())


async def test_drafter_parallel_preserves_order_and_time():
    import asyncio
    import time as _t

    import re as _re

    class StaggeredLLM(FakeLLM):
        """Content-aware double: first sub-question responds slowest — a sequential drafter
        would still order correctly, so the TIME assert is what proves parallelism."""
        async def chat_json(self, model, messages, schema, max_tokens=4096):
            self.prompts.append(messages)
            flat = str(messages)
            i = int(_re.search(r"Question (\d)\?", flat).group(1))
            await asyncio.sleep(0.15 - 0.02 * i)
            return {"claims": [{"text": f"claim q{i}", "citation_urls": [f"https://a.com/{i}"]}]}

    subs = [SubQuestion(id=f"q{i}", text=f"Question {i}?") for i in range(1, 7)]
    plan6 = PLAN.model_copy(update={"sub_questions": subs})
    sources6 = [Source(url=f"https://a.com/{i}", title=f"A{i}", content="c", sub_question_id=f"q{i}")
                for i in range(1, 7)]
    llm = StaggeredLLM()
    t0 = _t.monotonic()
    out = await draft_claims("b", plan6, sources6, {}, llm, "m-d")
    elapsed = _t.monotonic() - t0
    texts = [c.text for c in out]
    assert texts == [f"claim q{i}" for i in range(1, 7)]  # plan order, not completion order
    assert elapsed < 0.35, f"drafter still sequential: {elapsed:.2f}s"  # parallel ≈0.15s, sequential ≈0.6s
