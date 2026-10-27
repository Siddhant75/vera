import json

import pytest

from app import telemetry


@pytest.fixture(autouse=True)
def _reset_telemetry():
    telemetry.telemetry.reset()
    yield
    telemetry.telemetry.reset()


class FakeLLM:
    """Scripted TokenFactoryClient double. Records prompts; pops scripted results."""

    def __init__(self, responses=None):
        self.prompts: list[list[dict]] = []
        self.responses: list = list(responses or [])
        self.models_used: list[str] = []

    def queue(self, *responses):
        self.responses.extend(responses)

    async def chat(self, model, messages, max_tokens=2000, json_schema=None):
        self.prompts.append(messages)
        self.models_used.append(model)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return json.dumps(r)

    async def chat_json(self, model, messages, schema):
        self.prompts.append(messages)
        self.models_used.append(model)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeTavily:
    """Scripted TavilyClient double."""

    def __init__(self, results=None):
        self.queries: list[str] = []
        self.results: dict[str, list[dict]] = dict(results or {})

    async def search(self, query, max_results=5):
        self.queries.append(query)
        return self.results.get(query, [])

