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
                       profile: dict, llm: TokenFactoryClient, model: str) -> list[Claim]:
    by_q: dict[str, list[Source]] = {}
    for s in sources:
        by_q.setdefault(s.sub_question_id, []).append(s)

    out: list[Claim] = []
    n = 0
    for sq in plan.sub_questions:
        q_sources = by_q.get(sq.id, [])
        if not q_sources:
            continue  # no evidence → no claims, no hallucinated fill
        allowed = {s.url for s in q_sources}
        evidence = "\n\n".join(
            f"URL: {s.url}\nTITLE: {s.title}\nCONTENT: {s.content[:1200]}" for s in q_sources
        )
        data = await llm.chat_json(model, [
            {"role": "system", "content": (
                f"You are a research drafter writing for a {profile.get('persona', 'engineer')}. "
                "Extract the LOAD-BEARING factual claims from ONLY the provided sources — at most 5 "
                "per sub-question, the ones that actually move the decision. Skip trivia. Every claim "
                "must cite the exact source URLs that support it."
            )},
            {"role": "user", "content": f"Brief: {brief}\nSub-question: {sq.text}\n\nSources:\n{evidence}"},
        ], DRAFT_SCHEMA)
        for item in data.get("claims", [])[:5]:
            cited = [u for u in item.get("citation_urls", []) if u in allowed]
            if not cited:
                continue
            n += 1
            out.append(Claim(id=f"c{n}", sub_question_id=sq.id, text=item["text"], citation_urls=cited))
    return out
