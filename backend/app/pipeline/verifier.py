import asyncio

from app.llm import TokenFactoryClient
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
                        tavily: TavilyClient) -> list[Verdict]:
    by_q: dict[str, list[Source]] = {}
    for s in sources:
        by_q.setdefault(s.sub_question_id, []).append(s)

    async def _ask(model: str, claim: Claim, evidence: str) -> dict:
        try:
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
            evidence = _evidence([*by_q.get(claim.sub_question_id, []), *[
                Source(url=w["url"], title=w["title"], content=w["content"], sub_question_id=claim.sub_question_id)
                for w in web
            ]])
            round1 = await asyncio.gather(*(_ask(m, claim, evidence) for m in models))
            web_checked = True
        return Verdict(
            claim_id=claim.id,
            verdict=_resolve(round1),
            reason="; ".join(f"{m}: {r.get('reason', '')}" for m, r in zip(models, round1)),
            model=",".join(models),
            web_checked=web_checked,
        )

    out = list(await asyncio.gather(*(_verify_one(c) for c in claims)))
    telemetry.add(claims_verified=len(out))
    return out
