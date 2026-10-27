from app.models import (
    Claim,
    ReportSection,
    ResearchPlan,
    ResearchReport,
    Source,
    SubQuestion,
    Verdict,
)


def test_research_plan_round_trip():
    p = ResearchPlan(
        brief="b",
        persona="engineer",
        topic_key="k",
        sub_questions=[SubQuestion(id="q1", text="t")],
    )
    dump = p.model_dump()
    assert ResearchPlan(**dump) == p


def test_source_and_claim_defaults():
    s = Source(url="u", title="t", content="c", sub_question_id="q1")
    assert s.trust == 1.0
    c = Claim(id="c1", sub_question_id="q1", text="x", citation_urls=["u"])
    assert c.citation_urls == ["u"]


def test_verdict_web_checked_default_false():
    v = Verdict(claim_id="c1", verdict="supported", reason="r", model="m")
    assert v.web_checked is False


def test_report_defaults_and_round_trip():
    r = ResearchReport(
        brief="b",
        persona="founder",
        topic_key="k",
        sections=[
            ReportSection(sub_question="sq", narrative="n", claims=[])
        ],
        open_questions=["o1"],
        verdict_summary={"supported": 2, "disputed": 1},
    )
    assert r.changes == []
    assert r.claim_verdicts == {}
    assert ResearchReport(**r.model_dump()) == r
