from app.llm import TokenFactoryClient
from app.memory import Memory
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
        p = await plan(brief, active_persona, tk, profile, prior, llm, llm.planner_model)

        stage["current"] = "searching"
        await emit({"run_id": run_id, "stage": "searching", "payload": {
            "sub_questions": [sq.text for sq in p.sub_questions]}})
        sources = await search_sources(p, tavily, memory.trust_multiplier)

        stage["current"] = "drafting"
        await emit({"run_id": run_id, "stage": "drafting", "payload": {"source_count": len(sources)}})
        claims = await draft_claims(brief, p, sources, profile, llm, llm.drafter_model)

        stage["current"] = "verifying"
        await emit({"run_id": run_id, "stage": "verifying", "payload": {"claim_count": len(claims)}})
        verdicts = await verify_claims(claims, sources, llm.verifier_models, llm, tavily,
                                       trust_fn=memory.trust_multiplier,
                                       flagged_claims=memory.negative_claim_texts())

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
