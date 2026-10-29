from pydantic import BaseModel, Field


class SubQuestion(BaseModel):
    id: str
    text: str
    reuse_prior_sq: str | None = None  # delta mode: name of prior section to reuse verbatim


class ResearchPlan(BaseModel):
    brief: str
    persona: str
    topic_key: str
    sub_questions: list[SubQuestion]
    coverage: list[dict] = Field(default_factory=list)  # {requirement, sq_ids}


class Source(BaseModel):
    url: str
    title: str
    content: str
    sub_question_id: str
    trust: float = 1.0


class Claim(BaseModel):
    id: str
    sub_question_id: str
    text: str
    citation_urls: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    claim_id: str
    verdict: str  # "supported" | "contradicted" | "disputed"
    reason: str
    model: str
    web_checked: bool = False
    votes: list[dict] = Field(default_factory=list)  # final round: {model, verdict, reason} per verifier model
    prosecution: str = ""  # prosecutor's counter-evidence text, capped 800 chars


class ReportSection(BaseModel):
    sub_question: str
    narrative: str
    claims: list[Claim]


class ResearchReport(BaseModel):
    brief: str
    persona: str
    topic_key: str
    sections: list[ReportSection]
    open_questions: list[str] = Field(default_factory=list)
    verdict_summary: dict[str, int] = Field(default_factory=dict)
    claim_verdicts: dict[str, str] = Field(default_factory=dict)  # claim_id → final verdict
    claim_proofs: dict[str, dict] = Field(default_factory=dict)   # claim_id → {verdict, reason, web_checked}
    sources_unused: list[dict] = Field(default_factory=list)      # fetched but uncited: {url, title}
    changes: list[str] = Field(default_factory=list)  # delta mode: vs prior report
