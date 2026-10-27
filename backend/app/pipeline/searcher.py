import asyncio

from app.memory import domain_of
from app.models import ResearchPlan, Source
from app.search import TavilyClient


async def _one(sq, tavily: TavilyClient, trust_fn) -> list[Source]:
    results = await tavily.search(sq.text)
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
                         trust_fn) -> list[Source]:
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(_one(sq, tavily, trust_fn)) for sq in plan.sub_questions]
    return [src for t in tasks for src in t.result()]
