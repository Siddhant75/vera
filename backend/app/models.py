from pydantic import BaseModel, Field


class SubQuestion(BaseModel):
    id: str
    text: str


class ResearchPlan(BaseModel):
    brief: str
    persona: str
    topic_key: str
    sub_questions: list[SubQuestion]


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
    changes: list[str] = Field(default_factory=list)  # delta mode: vs prior report
