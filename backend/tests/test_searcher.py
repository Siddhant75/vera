from conftest import FakeTavily

from app.models import ResearchPlan, SubQuestion
from app.pipeline.searcher import search_sources

PLAN = ResearchPlan(
    brief="b", persona="engineer", topic_key="k",
    sub_questions=[SubQuestion(id="q1", text="What is X?"), SubQuestion(id="q2", text="Why X?")],
)

RESULTS = {
    "What is X?": [
        {"url": "https://good.com/a", "title": "A", "content": "ca"},
        {"url": "https://excluded.com/b", "title": "B", "content": "cb"},
        {"url": "https://plain.net/c", "title": "C", "content": "cc"},
    ],
    "Why X?": [{"url": "https://good.com/d", "title": "D", "content": "cd"}],
}


def trust_fn(domain: str) -> float:
    return {"good.com": 2.0, "excluded.com": 0.0}.get(domain, 1.0)


async def test_sources_tagged_and_ordered():
    tavily = FakeTavily(RESULTS)
    out = await search_sources(PLAN, tavily, trust_fn)
    q1 = [s for s in out if s.sub_question_id == "q1"]
    q2 = [s for s in out if s.sub_question_id == "q2"]
    assert [s.url for s in q1] == ["https://good.com/a", "https://plain.net/c"]
    assert q1[0].trust == 2.0 and q1[1].trust == 1.0
    assert [s.url for s in q2] == ["https://good.com/d"]
    assert q2[0].sub_question_id == "q2"


async def test_excluded_domain_dropped():
    tavily = FakeTavily(RESULTS)
    out = await search_sources(PLAN, tavily, trust_fn)
    assert all("excluded.com" not in s.url for s in out)


async def test_all_excluded_contributes_zero_sources():
    tavily = FakeTavily({"What is X?": [{"url": "https://excluded.com/b", "title": "B", "content": "cb"}]})
    out = await search_sources(PLAN, tavily, trust_fn)
    assert all(s.sub_question_id != "q1" for s in out)
