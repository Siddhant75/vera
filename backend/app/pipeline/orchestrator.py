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
                       emit) -> dict:
    stage = {"current": "planning"}
    profile = memory.get_profile()
    active_persona = persona or profile.get("persona", "engineer")
    tk = resolve_topic_key(topic, brief)
    prior = memory.last_report_for_topic(tk) if delta else None  # missing prior → silent full run
    try:
        await emit({"run_id": run_id, "stage": "planning", "payload": {"brief": brief}})
        prior_art = memory.prior_artifacts_for_topic(tk) if (delta and prior) else None
        p = await plan(brief, active_persona, tk, profile, prior, llm, llm.planner_model)

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
        sources = await search_sources(search_plan, tavily, memory.trust_multiplier)

        stage["current"] = "drafting"
        await emit({"run_id": run_id, "stage": "drafting", "payload": {"source_count": len(sources)}})
        claims = await draft_claims(brief, search_plan, sources, profile, llm, llm.drafter_model)

        stage["current"] = "verifying"
        await emit({"run_id": run_id, "stage": "verifying", "payload": {"claim_count": len(claims)}})
        verdicts = await verify_claims(claims, sources, llm.verifier_models, llm, tavily,
                                       trust_fn=memory.trust_multiplier,
                                       flagged_claims=memory.negative_claim_texts())

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
                                  sources, prior, llm, llm.planner_model)

        memory.save_run(brief, active_persona, tk, report.model_dump(), run_uuid=run_id)
        memory.save_verdicts(run_id, [v.model_dump() for v in verdicts])
        await emit({"run_id": run_id, "stage": "done", "payload": {"report": report.model_dump()}})
        await emit({"run_id": run_id, "stage": END, "payload": {}})
        return report
    except Exception as exc:
        await emit({"run_id": run_id, "stage": "error",
                    "payload": {"failed_stage": stage["current"], "detail": str(exc)}})
        await emit({"run_id": run_id, "stage": END, "payload": {}})
