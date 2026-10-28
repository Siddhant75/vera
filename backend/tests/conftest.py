import json

import pytest

from app import telemetry


@pytest.fixture(autouse=True)
def _reset_telemetry():
    telemetry.telemetry.reset()
    yield
    telemetry.telemetry.reset()


class FakeLLM:
    """Scripted TokenFactoryClient double. Records prompts; pops scripted results.
    `model_responses` keys by model name (pops first from model queue, else shared)."""

    def __init__(self, responses=None, model_responses=None, planner_model="planner",
                 drafter_model=None, verifier_models=None):
        self.prompts: list[list[dict]] = []
        self.responses: list = list(responses or [])
        self.model_responses: dict[str, list] = {k: list(v) for k, v in (model_responses or {}).items()}
        self.models_used: list[str] = []
        self.planner_model = planner_model
        self.drafter_model = drafter_model or planner_model
        self.verifier_models = verifier_models or []

    def queue(self, *responses):
        self.responses.extend(responses)

    def _next(self, model):
        q = self.model_responses.get(model)
        r = q.pop(0) if q else self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    async def chat(self, model, messages, max_tokens=2000, json_schema=None):
        self.prompts.append(messages)
        self.models_used.append(model)
        return json.dumps(self._next(model))

    async def chat_json(self, model, messages, schema, max_tokens=4096):
        self.prompts.append(messages)
        self.models_used.append(model)
        return self._next(model)


class FakeTavily:
    """Scripted TavilyClient double."""

    def __init__(self, results=None):
        self.queries: list[str] = []
        self.results: dict[str, list[dict]] = dict(results or {})

    async def search(self, query, max_results=5, role="grounding"):
        self.queries.append(query)
        return self.results.get(query, [])

