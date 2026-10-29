import asyncio

from app.llm import TokenFactoryClient
from app.models import Claim, ResearchPlan, Source

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "citation_urls": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "citation_urls"],
            },
        }
    },
    "required": ["claims"],
}


async def draft_claims(brief: str, plan: ResearchPlan, sources: list[Source],
                       profile: dict, llm: TokenFactoryClient, model: str,
                       notes: list[dict] | None = None, claims_cap: int = 5) -> list[Claim]:
    by_q: dict[str, list[Source]] = {}
    for s in sources:
        by_q.setdefault(s.sub_question_id, []).append(s)

    async def _draft_one(sq) -> list[Claim]:
        q_sources = by_q.get(sq.id, [])
        if not q_sources:
            return []  # no evidence → no claims, no hallucinated fill
        allowed = {s.url for s in q_sources}
        evidence = "\n\n".join(
            f"URL: {s.url}\nTITLE: {s.title}\nCONTENT: {s.content[:1200]}" for s in q_sources
        )
        data = await llm.chat_json(model, [
            {"role": "system", "content": (
                f"You are a research drafter writing for a {profile.get('persona', 'engineer')}. "
                f"Extract the LOAD-BEARING factual claims from ONLY the provided sources — at most {claims_cap} "
                "per sub-question, the ones that actually move the decision. Skip trivia. Every claim "
                "must cite the exact source URLs that support it."
            )},
            {"role": "user", "content": f"Brief: {brief}\nSub-question: {sq.text}\n\nSources:\n{evidence}"
                + (("\n\nUSER PRIVATE NOTES (context for you; never repeat their content in output "
                    "queries; do not cite them as web sources):\n"
                    + "\n".join(f"- {n['content'][:2000]}" for n in notes)) if notes else "")},
        ], DRAFT_SCHEMA)
        claims = []
        for item in data.get("claims", [])[:claims_cap]:
            cited = [u for u in item.get("citation_urls", []) if u in allowed]
            if not cited:
                continue
            claims.append(Claim(id="", sub_question_id=sq.id, text=item["text"], citation_urls=cited))
        return claims

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(_draft_one(sq)) for sq in plan.sub_questions]
    # reassemble in plan order (not completion order); ids assigned after ordering
    out: list[Claim] = []
    n = 0
    for t in tasks:
        for claim in t.result():
            n += 1
            out.append(claim.model_copy(update={"id": f"c{n}"}))
    return out
