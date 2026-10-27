import asyncio

from app.llm import TokenFactoryClient
from app.memory import domain_of
from app.models import Claim, Source, Verdict
from app.search import TavilyClient
from app.telemetry import telemetry

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"enum": ["supported", "contradicted", "uncertain"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
}


def _evidence(sources: list[Source]) -> str:
    return "\n\n".join(f"URL: {s.url}\nTITLE: {s.title}\nCONTENT: {s.content}" for s in sources) or "(no sources)"


def _resolve(round_verdicts: list[dict]) -> str:
    vs = [r.get("verdict", "uncertain") for r in round_verdicts]
    if all(v == "supported" for v in vs):
        return "supported"
    if any(v == "contradicted" for v in vs):
        return "contradicted"
    return "disputed"


async def verify_claims(claims: list[Claim], sources: list[Source],
                        models: list[str], llm: TokenFactoryClient,
                        tavily: TavilyClient, trust_fn=None,
                        max_concurrency: int = 6) -> list[Verdict]:
    sem = asyncio.Semaphore(max_concurrency)
    by_q: dict[str, list[Source]] = {}
    for s in sources:
        by_q.setdefault(s.sub_question_id, []).append(s)

    async def _ask(model: str, claim: Claim, evidence: str) -> dict:
        try:
            async with sem:
                return await llm.chat_json(model, [
                    {"role": "system", "content": (
                        "You are an adversarial fact verifier. Decide whether the claim is supported, "
                        "contradicted, or uncertain given ONLY the evidence. Be strict."
                    )},
                    {"role": "user", "content": f"Claim: {claim.text}\n\nEvidence:\n{evidence}"},
                ], VERDICT_SCHEMA)
        except Exception:
            return {"verdict": "uncertain", "reason": "model error"}

    async def _verify_one(claim: Claim) -> Verdict:
        evidence = _evidence(by_q.get(claim.sub_question_id, []))
        round1 = await asyncio.gather(*(_ask(m, claim, evidence) for m in models))
        web_checked = False
        if not all(r.get("verdict") == "supported" for r in round1):
            web = await tavily.search(claim.text)
            web_sources = []
            for w in web:
                domain = domain_of(w["url"])
                if trust_fn and trust_fn(domain) <= 0.0:
                    continue  # excluded domains never become verification evidence
                web_sources.append(Source(url=w["url"], title=w["title"], content=w["content"],
                                          sub_question_id=claim.sub_question_id))
            evidence = _evidence([*by_q.get(claim.sub_question_id, []), *web_sources])
            round1 = await asyncio.gather(*(_ask(m, claim, evidence) for m in models))
            web_checked = True
        return Verdict(
            claim_id=claim.id,
            verdict=_resolve(round1),
            reason="; ".join(f"{m}: {r.get('reason', '')}" for m, r in zip(models, round1)),
            model=",".join(models),
            web_checked=web_checked,
        )

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(_verify_one(c)) for c in claims]
    out = [t.result() for t in tasks]
    telemetry.add(claims_verified=len(out))
    return out
