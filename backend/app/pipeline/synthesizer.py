from app.llm import TokenFactoryClient
from app.models import Claim, ResearchPlan, ResearchReport, ReportSection, Source, Verdict

SECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["narrative", "open_questions"],
}

CHANGES_SCHEMA = {
    "type": "object",
    "properties": {"changes": {"type": "array", "items": {"type": "string"}}},
    "required": ["changes"],
}


async def synthesize(brief: str, persona: str, topic_key_in: str, plan: ResearchPlan,
                     claims: list[Claim], verdicts: list[Verdict], sources: list[Source],
                     prior_report: dict | None, llm: TokenFactoryClient,
                     model: str) -> ResearchReport:
    verdict_by_claim = {v.claim_id: v for v in verdicts}
    claims_by_q: dict[str, list[Claim]] = {}
    for c in claims:
        claims_by_q.setdefault(c.sub_question_id, []).append(c)
    sources_by_q: dict[str, list[Source]] = {}
    for s in sources:
        sources_by_q.setdefault(s.sub_question_id, []).append(s)

    changes: list[str] = []
    if prior_report is not None:
        data = await llm.chat_json(model, [
            {"role": "system", "content": "You compare two research reports. Return JSON."},
            {"role": "user", "content": (
                f"Brief: {brief}\n\nPrior report sections:\n{prior_report.get('sections', [])}\n\n"
                f"New claims with verdicts:\n"
                + "\n".join(f"- {c.text} [{verdict_by_claim.get(c.id).verdict}]" for c in claims)
            )},
        ], CHANGES_SCHEMA)
        changes = data.get("changes", [])

    sections: list[ReportSection] = []
    open_questions: list[str] = []
    for sq in plan.sub_questions:
        q_claims = claims_by_q.get(sq.id, [])
        if not q_claims:
            sections.append(ReportSection(
                sub_question=sq.text,
                narrative="No sources found for this question; nothing verified to report.",
                claims=[],
            ))
            open_questions.append(sq.text)
            continue
        claim_lines = []
        for c in q_claims:
            v = verdict_by_claim.get(c.id)
            label = v.verdict if v else "unverified"
            claim_lines.append(f"- {c.text} [VERDICT: {label}] (sources: {', '.join(c.citation_urls)})")
        data = await llm.chat_json(model, [
            {"role": "system", "content": (
                f"You are a research synthesizer writing for a {persona}. Write a coherent narrative "
                "section. Every claim carries its verification verdict — state disputed or contradicted "
                "claims with that label, never silently. Return JSON."
            )},
            {"role": "user", "content": f"Brief: {brief}\nSub-question: {sq.text}\n\nVerified claims:\n" + "\n".join(claim_lines)},
        ], SECTION_SCHEMA)
        sections.append(ReportSection(sub_question=sq.text, narrative=data["narrative"], claims=q_claims))
        open_questions.extend(data.get("open_questions", []))

    summary: dict[str, int] = {}
    claim_verdicts: dict[str, str] = {}
    claim_proofs: dict[str, dict] = {}
    for v in verdicts:
        summary[v.verdict] = summary.get(v.verdict, 0) + 1
        claim_verdicts[v.claim_id] = v.verdict
        claim_proofs[v.claim_id] = {
            "verdict": v.verdict, "reason": v.reason, "web_checked": v.web_checked,
        }

    return ResearchReport(
        brief=brief, persona=persona, topic_key=topic_key_in,
        sections=sections, open_questions=open_questions,
        verdict_summary=summary, claim_verdicts=claim_verdicts,
        claim_proofs=claim_proofs, changes=changes,
    )
