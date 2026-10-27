import json

from conftest import FakeLLM, FakeTavily

from app.models import Claim, Source
from app.pipeline.verifier import verify_claims

CLAIM = Claim(id="c1", sub_question_id="q1", text="X is true", citation_urls=["https://a.com/1"])
SOURCES = [Source(url="https://a.com/1", title="A", content="content of a", sub_question_id="q1")]

SUP = {"verdict": "supported", "reason": "evidence says so"}
CON = {"verdict": "contradicted", "reason": "evidence says no"}
UNC = {"verdict": "uncertain", "reason": "unclear"}


def verdict(model, v, web=False):
    return {"claim_id": "c1", "verdict": v, "reason": r"reason", "model": model, "web_checked": web}


async def test_all_supported_no_web_check():
    llm = FakeLLM(model_responses={"mA": [SUP], "mB": [SUP]})
    tavily = FakeTavily()
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, tavily)
    assert out[0].verdict == "supported"
    assert out[0].web_checked is False
    assert tavily.queries == []
    assert llm.models_used == ["mA", "mB"]  # exactly one call per model


async def test_disagreement_triggers_web_recheck():
    llm = FakeLLM(model_responses={
        "mA": [SUP, SUP],
        "mB": [CON, CON],
    })
    tavily = FakeTavily({"X is true": [{"url": "https://w.com/x", "title": "W", "content": "web evidence"}]})
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, tavily)
    assert tavily.queries == ["X is true"]
    assert out[0].web_checked is True
    assert out[0].verdict == "contradicted"  # any contradicted wins
    assert llm.models_used == ["mA", "mB", "mA", "mB"]  # re-asked


async def test_supported_plus_uncertain_is_disputed():
    llm = FakeLLM(model_responses={"mA": [SUP, SUP], "mB": [UNC, UNC]})
    tavily = FakeTavily()
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, tavily)
    assert out[0].web_checked is True
    assert out[0].verdict == "disputed"


async def test_model_error_treated_as_uncertain():
    llm = FakeLLM(model_responses={"mA": [SUP, SUP], "mB": [ValueError("boom"), UNC]})
    tavily = FakeTavily()
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, tavily)
    assert out[0].verdict == "disputed"
    assert out[0].web_checked is True


async def test_prompt_contains_claim_and_evidence():
    llm = FakeLLM(model_responses={"mA": [SUP], "mB": [SUP]})
    await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, FakeTavily())
    flat = str(llm.prompts[0])
    assert "X is true" in flat
    assert "content of a" in flat
