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
    llm = FakeLLM(model_responses={"mA": [PROSECUTE_CLEAN, SUP], "mB": [SUP]})
    tavily = FakeTavily()
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, tavily)
    assert out[0].verdict == "supported"
    assert out[0].web_checked is False  # prosecutor clean, no refutation query
    assert tavily.queries == []
    assert llm.models_used == ["mA", "mA", "mB"]  # prosecutor pass, then vote


async def test_disagreement_triggers_web_recheck():
    llm = FakeLLM(model_responses={
        "mA": [PROSECUTE, SUP, SUP],
        "mB": [CON, CON],
    })
    tavily = FakeTavily({"X is true": [{"url": "https://w.com/x", "title": "W", "content": "web evidence"}]})
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, tavily)
    assert "X is true" in tavily.queries  # prosecutor searched "X is wrong" first
    assert out[0].web_checked is True
    assert out[0].verdict == "contradicted"  # any contradicted wins
    assert llm.models_used == ["mA", "mA", "mB", "mA", "mB"]  # prosecutor, vote, re-vote


async def test_supported_plus_uncertain_is_disputed():
    llm = FakeLLM(model_responses={"mA": [PROSECUTE, SUP, SUP], "mB": [UNC, UNC]})
    tavily = FakeTavily()
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, tavily)
    assert out[0].web_checked is True
    assert out[0].verdict == "disputed"


async def test_model_error_treated_as_uncertain():
    llm = FakeLLM(model_responses={"mA": [PROSECUTE, SUP, SUP], "mB": [ValueError("boom"), UNC]})
    tavily = FakeTavily()
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, tavily)
    assert out[0].verdict == "disputed"
    assert out[0].web_checked is True


async def test_prompt_contains_claim_and_evidence():
    llm = FakeLLM(model_responses={"mA": [PROSECUTE_CLEAN, SUP], "mB": [SUP]})
    await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, FakeTavily())
    flat = str(llm.prompts[0])
    assert "X is true" in flat
    assert "content of a" in flat


async def test_web_recheck_respects_trust_exclusion():
    llm = FakeLLM(model_responses={"mA": [PROSECUTE, SUP, SUP], "mB": [CON, CON]})
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


async def test_flagged_claims_raise_strictness():
    llm = FakeLLM(model_responses={"mA": [SUP], "mB": [SUP]})
    await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, FakeTavily(),
                        flagged_claims=["K8s is always cheaper"])
    assert "K8s is always cheaper" in str(llm.prompts[1:])  # voters carry strictness, not prosecutor


PROSECUTE = {"refutation_query": "X is wrong", "suspicions": "costs may be hidden"}
PROSECUTE_CLEAN = {"refutation_query": None, "suspicions": ""}

async def test_prosecutor_runs_before_vote():
    llm = FakeLLM(model_responses={"mA": [PROSECUTE, SUP], "mB": [SUP]})
    tavily = FakeTavily()
    await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, tavily)
    assert llm.models_used == ["mA", "mA", "mB"]  # prosecutor (first model) then vote


async def test_prosecutor_query_drives_search():
    llm = FakeLLM(model_responses={"mA": [PROSECUTE, SUP], "mB": [SUP]})
    tavily = FakeTavily({"X is wrong": [{"url": "https://allowed.com/r", "title": "R", "content": "refuting data"}]})
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, tavily)
    assert "X is wrong" in tavily.queries
    assert "refuting data" in str(llm.prompts[1:])  # refutation evidence reaches voters
    assert out[0].web_checked is True


async def test_prosecutor_no_query_no_search():
    llm = FakeLLM(model_responses={"mA": [{"refutation_query": None, "suspicions": "clean"}, SUP], "mB": [SUP]})
    tavily = FakeTavily()
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, tavily)
    assert tavily.queries == []
    assert out[0].verdict == "supported"


async def test_prosecutor_skips_search_when_budget_out():
    from app.budget import SearchBudget
    llm = FakeLLM(model_responses={"mA": [PROSECUTE, SUP], "mB": [SUP]})
    b = SearchBudget(0)
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, FakeTavily(), budget=b)
    assert out[0].verdict == "supported"  # vote unaffected - refutation search optional
    assert "budget-limited" not in out[0].reason


async def test_recheck_skipped_when_budget_out():
    from app.budget import SearchBudget
    llm = FakeLLM(model_responses={"mA": [PROSECUTE_CLEAN, SUP], "mB": [UNC]})
    b = SearchBudget(0)
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, FakeTavily(), budget=b)
    assert "budget-limited" in out[0].reason
    assert out[0].verdict == "disputed"  # stands on existing evidence


async def test_evidence_capped_8_sources_800_chars():
    sources = [Source(url=f"https://a.com/{i}", title=f"T{i}", content="y" * 2000, sub_question_id="q1")
               for i in range(12)]
    llm = FakeLLM(model_responses={"mA": [PROSECUTE_CLEAN, SUP], "mB": [SUP]})
    await verify_claims([CLAIM], sources, ["mA", "mB"], llm, FakeTavily())
    vote_prompt = str(llm.prompts[1])
    assert vote_prompt.count("https://a.com/") <= 8
    assert "y" * 801 not in vote_prompt


async def test_verdict_carries_votes_and_prosecution():
    llm = FakeLLM(model_responses={"mA": [PROSECUTE, SUP, SUP], "mB": [CON, CON]})
    tavily = FakeTavily({"X is wrong": [{"url": "https://w.com/x", "title": "W", "content": "web evidence"}]})
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, tavily)
    v0 = out[0]
    assert v0.votes == [
        {"model": "mA", "verdict": "supported", "reason": "evidence says so"},
        {"model": "mB", "verdict": "contradicted", "reason": "evidence says no"},
    ]  # final deciding round (post-recheck)
    assert "PROSECUTOR SUSPICIONS: costs may be hidden" in v0.prosecution
    assert "REFUTATION EVIDENCE" in v0.prosecution


async def test_budget_limited_verdict_carries_round1_votes():
    from app.budget import SearchBudget
    llm = FakeLLM(model_responses={"mA": [PROSECUTE_CLEAN, SUP], "mB": [UNC]})
    out = await verify_claims([CLAIM], SOURCES, ["mA", "mB"], llm, FakeTavily(), budget=SearchBudget(0))
    assert out[0].votes == [
        {"model": "mA", "verdict": "supported", "reason": "evidence says so"},
        {"model": "mB", "verdict": "uncertain", "reason": "unclear"},
    ]
    assert out[0].prosecution == ""
