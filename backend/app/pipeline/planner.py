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
                "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["id", "text"],
            },
        }
    },
    "required": ["sub_questions"],
}


def topic_key(topic_or_brief: str) -> str:
    slug = re.sub(r"[^a-z0-9 ]", " ", topic_or_brief.lower())
    slug = re.sub(r" +", " ", slug).strip()[:60].strip()
    return slug.replace(" ", "-")


async def plan(brief: str, persona: str, topic_key_in: str, profile: dict,
               prior_report: dict | None, llm: TokenFactoryClient, model: str) -> ResearchPlan:
    prior_note = ""
    if prior_report:
        open_qs = "\n".join(f"- {q}" for q in prior_report.get("open_questions", []))
        prior_note = (
            f"\n\nThe user researched this topic before. Previous open questions:\n{open_qs}\n"
            "Focus the sub-questions on changes, updates and resolving those open questions."
        )
    system = (
        f"You are a research planner. The user is a {persona}. Phrase sub-questions for "
        f"their expertise level and what they care about. Return JSON matching the schema."
    )
    user = f"Research brief: {brief}{prior_note}"
    data = await llm.chat_json(model, [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], PLAN_SCHEMA)
    subs = [SubQuestion(id=f"q{i+1}", text=item["text"])
            for i, item in enumerate(data.get("sub_questions", []))]
    return ResearchPlan(brief=brief, persona=persona, topic_key=topic_key_in, sub_questions=subs)
