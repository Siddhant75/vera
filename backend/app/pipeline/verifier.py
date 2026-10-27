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

PROSECUTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "refutation_query": {"type": ["string", "null"]},
        "suspicions": {"type": "string"},
    },
    "required": ["refutation_query", "suspicions"],
}


def _evidence(sources: list[Source]) -> str:
    # Read narrow: top 8 trust-ranked sources, 800 chars each — output has a word cap,
    # so input gets one too. The rest of the fetched pool surfaces as unused sources.
    trimmed = sources[:8]
    return "\n\n".join(f"URL: {s.url}\nTITLE: {s.title}\nCONTENT: {s.content[:800]}" for s in trimmed) or "(no sources)"


def _resolve(round_verdicts: list[dict]) -> str:
    vs = [r.get("verdict", "uncertain") for r in round_verdicts]
    if all(v == "supported" for v in vs):
        return "supported"
    if any(v == "contradicted" for v in vs):
        return "contradicted"
    return "disputed"


def _web_sources(web: list[dict], sq_id: str, trust_fn) -> list[Source]:
    out = []
    for w in web:
        domain = domain_of(w["url"])
        if trust_fn and trust_fn(domain) <= 0.0:
            continue  # excluded domains never become verification evidence
        out.append(Source(url=w["url"], title=w["title"], content=w["content"], sub_question_id=sq_id))
    return out


async def verify_claims(claims: list[Claim], sources: list[Source],
                        models: list[str], llm: TokenFactoryClient,
                        tavily: TavilyClient, trust_fn=None,
                        max_concurrency: int = 6, flagged_claims: list[str] | None = None,
                        budget=None) -> list[Verdict]:
    sem = asyncio.Semaphore(max_concurrency)
    strictness = ""
    if flagged_claims:
        flagged = "\n".join(f"- {t}" for t in flagged_claims)
        strictness = (
            "\nThe user previously flagged similar claims as unhelpful or wrong — be extra strict "
            f"about claims of this kind:\n{flagged}"
        )

    async def _ask_raw(model: str, messages: list[dict], schema: dict) -> dict:
        try:
            async with sem:
                return await llm.chat_json(model, messages, schema)
        except Exception:
            return {"refutation_query": None, "suspicions": ""}

    async def _ask(model: str, claim: Claim, evidence: str) -> dict:
        try:
            async with sem:
                return await llm.chat_json(model, [
                    {"role": "system", "content": (
                        "You are an adversarial fact verifier. Decide whether the claim is supported, "
                        "contradicted, or uncertain given ONLY the evidence. Be strict." + strictness
                    )},
                    {"role": "user", "content": f"Claim: {claim.text}\n\nEvidence:\n{evidence}"},
                ], VERDICT_SCHEMA)
        except Exception:
            return {"verdict": "uncertain", "reason": "model error"}

    async def _prosecute(claim: Claim, evidence: str) -> str:
        # Active adversarial pass: hunt counter-evidence BEFORE voting, not just after disagreement.
        out = await _ask_raw(models[0], [
            {"role": "system", "content": (
                "You are a prosecutor. Your job is to find why this claim might be WRONG. "
                "If live web evidence could refute it, propose a refutation search query. "
                "If the claim looks solid, return null. Be skeptical."
            )},
            {"role": "user", "content": f"Claim: {claim.text}\n\nCurrent evidence:\n{evidence}"},
        ], PROSECUTOR_SCHEMA)
        parts = []
        if out.get("suspicions"):
            parts.append(f"PROSECUTOR SUSPICIONS: {out['suspicions']}")
        query = out.get("refutation_query")
        if query and (budget is None or budget.try_consume()):
            web = await tavily.search(query)
            for w in _web_sources(web, claim.sub_question_id, trust_fn):
                parts.append(f"REFUTATION EVIDENCE ({w.url}): {w.title} - {w.content[:800]}")
        elif query:
            parts.append("PROSECUTOR: search budget exhausted - refutation search skipped")
        return "\n".join(parts)

    async def _verify_one(claim: Claim) -> Verdict:
        base_evidence = _evidence(by_q.get(claim.sub_question_id, []))
        prosecution = await _prosecute(claim, base_evidence)
        evidence = base_evidence + (f"\n\n{prosecution}" if prosecution else "")
        round1 = await asyncio.gather(*(_ask(m, claim, evidence) for m in models))
        web_checked = bool(prosecution)
        if not all(r.get("verdict") == "supported" for r in round1):
            if budget is not None and not budget.try_consume():
                return Verdict(
                    claim_id=claim.id, verdict=_resolve(round1),
                    reason="; ".join(f"{m}: {r.get('reason', '')}" for m, r in zip(models, round1))
                           + " [budget-limited: web re-check skipped]",
                    model=",".join(models), web_checked=False,
                )
            web = await tavily.search(claim.text)
            web_srcs = _web_sources(web, claim.sub_question_id, trust_fn)
            evidence = _evidence([*by_q.get(claim.sub_question_id, []), *web_srcs])
            round1 = await asyncio.gather(*(_ask(m, claim, evidence) for m in models))
            web_checked = True
        return Verdict(
            claim_id=claim.id,
            verdict=_resolve(round1),
            reason="; ".join(f"{m}: {r.get('reason', '')}" for m, r in zip(models, round1)),
            model=",".join(models),
            web_checked=web_checked,
        )

    by_q: dict[str, list[Source]] = {}
    for s in sources:
        by_q.setdefault(s.sub_question_id, []).append(s)

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(_verify_one(c)) for c in claims]
    out = [t.result() for t in tasks]
    telemetry.add(claims_verified=len(out))
    return out
