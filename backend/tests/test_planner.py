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


def test_topic_key_slug():
    assert topic_key("Should we adopt Kubernetes?") == "should-we-adopt-kubernetes"
