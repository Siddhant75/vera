from conftest import FakeLLM

from app.pipeline.planner import plan, topic_key

SCHEMA_OK = {"sub_questions": [{"id": "a", "text": "What is X?"}, {"id": "b", "text": "Why X?"}]}

PROFILE = {"persona": "founder", "trusted_sources": [], "excluded_sources": []}

PRIOR = {"open_questions": ["is RAG still needed?"], "sections": []}


async def test_plan_parses_and_assigns_sequential_ids():
    llm = FakeLLM([SCHEMA_OK])
    p = await plan("Explain X", "founder", "explain-x", PROFILE, None, llm, "m-planner")
    assert [sq.id for sq in p.sub_questions] == ["q1", "q2"]
    assert [sq.text for sq in p.sub_questions] == ["What is X?", "Why X?"]
    assert p.topic_key == "explain-x"
    assert p.persona == "founder"


async def test_prompt_contains_persona_and_brief():
    llm = FakeLLM([SCHEMA_OK])
    await plan("Explain X", "founder", "k", PROFILE, None, llm, "m-planner")
    flat = str(llm.prompts[0])
    assert "founder" in flat
    assert "Explain X" in flat


async def test_prior_report_open_questions_in_prompt():
    llm = FakeLLM([SCHEMA_OK])
    await plan("Explain X", "founder", "k", PROFILE, PRIOR, llm, "m-planner")
    assert "is RAG still needed?" in str(llm.prompts[0])


async def test_empty_plan_raises():
    import pytest
    llm = FakeLLM([{"sub_questions": []}])
    with pytest.raises(ValueError, match="no sub-questions"):
        await plan("Explain X", "founder", "k", PROFILE, None, llm, "m-planner")


def test_topic_key_slug():
    assert topic_key("Should we adopt Kubernetes?") == "should-we-adopt-kubernetes"


async def test_profile_context_in_prompt():
    rich = dict(PROFILE, role_context="CTO of a 10-person startup",
                goals="ship ML API cheaply", expertise_notes="knows Docker, new to k8s")
    llm = FakeLLM([SCHEMA_OK])
    await plan("Explain X", "founder", "k", rich, None, llm, "m-planner")
    flat = str(llm.prompts[0])
    assert "CTO of a 10-person startup" in flat
    assert "ship ML API cheaply" in flat
    assert "knows Docker, new to k8s" in flat
