import re

from app.llm import TokenFactoryClient
from app.models import ResearchPlan, SubQuestion

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "sub_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "reuse_prior_sq": {"type": ["string", "null"]},
                },
                "required": ["id", "text"],
            },
        },
        "coverage": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "sq_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["requirement", "sq_ids"],
            },
        },
    },
    "required": ["sub_questions"],
}


def topic_key(topic_or_brief: str) -> str:
    slug = re.sub(r"[^a-z0-9 ]", " ", topic_or_brief.lower())
    slug = re.sub(r" +", " ", slug).strip()[:60].strip()
    return slug.replace(" ", "-")


async def plan(brief: str, persona: str, topic_key_in: str, profile: dict,
               prior_report: dict | None, llm: TokenFactoryClient, model: str,
               missed_requirements: list[str] | None = None,
               notes: list[dict] | None = None) -> ResearchPlan:
    prior_note = ""
    if prior_report:
        open_qs = "\n".join(f"- {q}" for q in prior_report.get("open_questions", []))
        prior_sections = "\n".join(
            f"- {s.get('sub_question', '')}" for s in prior_report.get("sections", [])
        )
        prior_note = (
            f"\n\nThe user researched this topic before. Prior sub-questions:\n{prior_sections}\n"
            f"Previous open questions:\n{open_qs}\n"
            "Focus the sub-questions on changes, updates and resolving those open questions. "
            "If a prior sub-question is still fully covered by the previous research and needs no "
            "fresh search, set reuse_prior_sq to that prior sub-question's exact text."
        )
    ctx = "\n".join(filter(None, [
        f"Role: {profile.get('role_context', '')}",
        f"Current goals: {profile.get('goals', '')}",
        f"Expertise: {profile.get('expertise_notes', '')}",
    ]))
    system = (
        f"You are a research planner. The user is a {persona}."
        + (f"\nAbout the user:\n{ctx}" if ctx else "")
        + "\nPhrase sub-questions for their expertise level and what they care about. "
          "At most 8 sub-questions. If the brief lists explicit bullet requirements, map every one "
          "to sub-questions via the coverage field. Return JSON matching the schema."
    )
    missed_note = ""
    if missed_requirements:
        missed_note = "\n\nMANDATORY: these explicitly requested items are NOT yet covered. " \
            "You MUST produce sub-questions answering each one:\n" + \
            "\n".join(f"- {r}" for r in missed_requirements)
    notes_note = ""
    if notes:
        block = "\n".join(f"- {n['content'][:2000]}" for n in notes)
        notes_note = ("\n\nUSER PRIVATE NOTES (private: never repeat their content in search "
                      f"queries; do not cite them as web sources):\n{block}")
    user = f"Research brief: {brief}{prior_note}{missed_note}{notes_note}"
    data = await llm.chat_json(model, [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], PLAN_SCHEMA)
    subs = [SubQuestion(id=f"q{i+1}", text=item["text"], reuse_prior_sq=item.get("reuse_prior_sq"))
            for i, item in enumerate(data.get("sub_questions", []))
            if item.get("text")]
    if not subs:
        raise ValueError("planner returned no sub-questions")
    if missed_requirements is not None:
        subs = subs[:8]
    coverage = [c for c in data.get("coverage", []) if c.get("requirement")]
    return ResearchPlan(brief=brief, persona=persona, topic_key=topic_key_in,
                        sub_questions=subs, coverage=coverage)
