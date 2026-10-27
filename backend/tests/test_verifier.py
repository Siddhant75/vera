import asyncio
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


async def test_web_recheck_respects_trust_exclusion():
    llm = FakeLLM(model_responses={"mA": [SUP, SUP], "mB": [CON, CON]})
    tavily = FakeTavily({"X is true": [
        {"url": "https://excluded.com/x", "title": "X", "content": "excluded evidence"},
        {"url": "https://allowed.com/y", "title": "Y", "content": "allowed evidence"},
    ]})
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, tavily,
                              trust_fn=lambda d: 0.0 if d == "excluded.com" else 1.0)
    recheck_prompts = llm.prompts[2:]  # after round-1 (one per model)
    assert "excluded evidence" not in str(recheck_prompts)
    assert "allowed evidence" in str(recheck_prompts)
    assert out[0].web_checked is True


async def test_concurrency_bounded():
    class InflightLLM(FakeLLM):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.inflight = 0
            self.max_inflight = 0

        async def chat_json(self, model, messages, schema):
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
            try:
                await asyncio.sleep(0.01)
                return await super().chat_json(model, messages, schema)
            finally:
                self.inflight -= 1

    claims = [Claim(id=f"c{i}", sub_question_id="q1", text=f"claim {i}", citation_urls=["https://a.com/1"])
              for i in range(1, 5)]
    llm = InflightLLM(model_responses={m: [SUP] for m in ("mA", "mB")})
    await verify_claims(claims, SOURCES, ["mA", "mB"], llm, FakeTavily(), max_concurrency=6)
    assert llm.max_inflight <= 6
