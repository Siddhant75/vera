import asyncio

from app.memory import domain_of
from app.models import ResearchPlan, Source
from app.search import TavilyClient


async def _one(sq, tavily: TavilyClient, trust_fn, budget=None, gate=None) -> list[Source]:
    if budget is not None and not budget.try_consume():
        return []  # search budget exhausted: sub-question degrades to zero sources, visibly
    query = gate(sq.text) if gate else sq.text
    results = await tavily.search(query, role="grounding")
    out = []
    for r in results:
        trust = trust_fn(domain_of(r["url"]))
        if trust <= 0.0:
            continue
        out.append(Source(url=r["url"], title=r["title"], content=r["content"],
                          sub_question_id=sq.id, trust=trust))
    out.sort(key=lambda s: s.trust, reverse=True)
    return out


async def search_sources(plan: ResearchPlan, tavily: TavilyClient,
                         trust_fn, budget=None, gate=None) -> list[Source]:
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(_one(sq, tavily, trust_fn, budget, gate)) for sq in plan.sub_questions]
    return [src for t in tasks for src in t.result()]
