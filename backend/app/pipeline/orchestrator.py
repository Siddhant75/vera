from app.budget import budget_for_brief
from app.llm import TokenFactoryClient
from app.memory import Memory
from app.models import Claim, Verdict
from app.pipeline.drafter import draft_claims
from app.pipeline.planner import plan, topic_key
from app.pipeline.searcher import search_sources
from app.pipeline.synthesizer import synthesize
from app.pipeline.verifier import verify_claims
from app.search import TavilyClient

END = "__end__"


def resolve_topic_key(topic: str, brief: str) -> str:
    return topic_key(topic) if topic else topic_key(brief)


async def run_research(run_id: str, brief: str, persona: str, topic: str, delta: bool,
                       llm: TokenFactoryClient, tavily: TavilyClient, memory: Memory,
                       emit, domain_prefs: dict | None = None, source: str = "manual") -> dict:
    stage = {"current": "planning"}
    from app.telemetry import telemetry as _tel
    t_start = _tel.snapshot()
    profile = memory.get_profile()
    active_persona = persona or profile.get("persona", "engineer")
    tk = resolve_topic_key(topic, brief)
    prior = memory.last_report_for_topic(tk) if delta else None  # missing prior → silent full run
    try:
        await emit({"run_id": run_id, "stage": "planning", "payload": {"brief": brief}})
        prior_art = memory.prior_artifacts_for_topic(tk) if (delta and prior) else None
        from app.brief import parse_requirements
        from app.privacy import safe_query
        requirements = parse_requirements(brief)
        notes = memory.list_notes(tk)
        gate = (lambda q: safe_query(q, [n["content"] for n in notes], fallback=tk)) if notes else None
        p = await plan(brief, active_persona, tk, profile, prior, llm, llm.planner_model, notes=notes)

        # Deterministic coverage gate: every parsed bullet must map to a sub-question.
        # LLM cannot skip this — code owns the check.
        def uncovered_reqs(p):
            covered = {c["requirement"].lower(): c["sq_ids"] for c in p.coverage}
            flat = " ".join(sq.text.lower() for sq in p.sub_questions)
            return [r for r in requirements
                    if not (covered.get(r.lower()) or any(w in flat for w in r.lower().split()[:4]))]

        uncovered = uncovered_reqs(p)
        if uncovered:
            stage["current"] = "planning"
            p = await plan(brief, active_persona, tk, profile, prior, llm, llm.planner_model,
                           missed_requirements=uncovered, notes=notes)
            uncovered = uncovered_reqs(p)
        if len(p.sub_questions) > 8:
            p = p.model_copy(update={"sub_questions": p.sub_questions[:8]})
        # tier ceilings: depth sizes the whole pipeline (personalization is orthogonal — persona/notes/trust apply at every tier)
        tier_ceiling = {"quick": 3, "standard": 5, "deep": 8}.get(p.depth, 5)
        if len(p.sub_questions) > tier_ceiling:
            p = p.model_copy(update={"sub_questions": p.sub_questions[:tier_ceiling]})

        # True delta: sub-questions marked reused skip search+draft+verify; prior claims + verdicts carried
        reused_sections: dict[str, dict] = {}
        fresh_subs = []
        if prior_art:
            for sq in p.sub_questions:
                if sq.reuse_prior_sq:
                    match = next((s for s in prior_art["sections"]
                                  if s.get("sub_question") == sq.reuse_prior_sq), None)
                    if match and match.get("claims"):
                        reused_sections[sq.id] = match
                        continue
                fresh_subs.append(sq)
        else:
            fresh_subs = list(p.sub_questions)

        stage["current"] = "searching"
        await emit({"run_id": run_id, "stage": "searching", "payload": {
            "sub_questions": [sq.text for sq in fresh_subs],
            "reused": [sq.text for sq in p.sub_questions if sq.id in reused_sections]}})
        search_plan = p.model_copy(update={"sub_questions": fresh_subs})
        from app.budget import SearchBudget
        from app.memory import clean_domains
        domain_prefs = domain_prefs or {"trusted": clean_domains(profile.get("trusted_sources", [])),
                                        "excluded": clean_domains(profile.get("excluded_sources", []))}
        budget = SearchBudget(budget_for_brief(brief, depth=p.depth))
        sources = await search_sources(search_plan, tavily, memory.trust_multiplier, budget=budget,
                                       gate=gate, domain_prefs=domain_prefs)

        stage["current"] = "drafting"
        await emit({"run_id": run_id, "stage": "drafting", "payload": {"source_count": len(sources)}})
        claims = await draft_claims(brief, search_plan, sources, profile, llm, llm.drafter_model,
                                    notes=notes,
                                    claims_cap={"quick": 3, "standard": 4, "deep": 5}.get(p.depth, 4))

        stage["current"] = "verifying"
        await emit({"run_id": run_id, "stage": "verifying", "payload": {"claim_count": len(claims)}})
        verdicts = await verify_claims(claims, sources, llm.verifier_models, llm, tavily,
                                       trust_fn=memory.trust_multiplier,
                                       flagged_claims=memory.negative_claim_texts(),
                                       budget=budget, gate=gate, domain_prefs=domain_prefs,
                                       tier=p.depth)

        # merge reused claims (ids prefixed r- to avoid collisions) + their prior verdicts
        for sq_id, section in reused_sections.items():
            for pc in section.get("claims", []):
                new_id = f"r-{pc['id']}"
                claims.append(Claim(id=new_id, sub_question_id=sq_id,
                                    text=pc.get("text", ""), citation_urls=pc.get("citation_urls", [])))
                pv = prior_art["verdicts"].get(pc["id"])
                verdicts.append(Verdict(claim_id=new_id,
                                        verdict=pv["verdict"] if pv else "unverified",
                                        reason=pv["reason"] if pv else "carried over from prior research",
                                        model=pv["model"] if pv else "prior",
                                        web_checked=pv["web_checked"] if pv else False))

        stage["current"] = "synthesizing"
        await emit({"run_id": run_id, "stage": "synthesizing", "payload": {}})
        report = await synthesize(brief, active_persona, tk, p, claims, verdicts,
                                  sources, prior, llm, llm.planner_model,
                                  uncovered=uncovered, notes_count=len(notes), depth=p.depth)

        memory.save_run(brief, active_persona, tk, report.model_dump(), run_uuid=run_id, source=source)
        memory.save_verdicts(run_id, [v.model_dump() for v in verdicts])
        memory.save_sources(run_id, [{"url": s.url, "title": s.title} for s in sources])
        from app.telemetry import telemetry
        t_now = telemetry.snapshot()
        await emit({"run_id": run_id, "stage": "done", "payload": {"report": report.model_dump(), "run_summary": {
            "searches_used": budget.used, "search_budget": budget.limit,
            "tf_tokens_run": t_now["tf_tokens"] - t_start["tf_tokens"],
            "claims": len(claims), "reused": len(reused_sections),
        }}})
        await emit({"run_id": run_id, "stage": END, "payload": {}})
        return report
    except Exception as exc:
        await emit({"run_id": run_id, "stage": "error",
                    "payload": {"failed_stage": stage["current"], "detail": str(exc)}})
        await emit({"run_id": run_id, "stage": END, "payload": {}})
