import json

import httpx

from app.telemetry import telemetry


class LLMError(Exception):
    pass


class TokenFactoryClient:
    """Nebius Token Factory client (OpenAI-compatible /chat/completions)."""

    def __init__(self, base_url: str, api_key: str, http: httpx.AsyncClient | None = None,
                 planner_model: str = "", drafter_model: str = "",
                 verifier_models: list[str] | None = None):
        self.planner_model = planner_model
        self.drafter_model = drafter_model or planner_model
        self.verifier_models = verifier_models or []
        if http is not None:
            http.base_url = base_url
            self._http = http
        else:
            self._http = httpx.AsyncClient(
                base_url=base_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=120,
            )

    async def chat(self, model: str, messages: list[dict], max_tokens: int = 2000,
                   json_schema: dict | None = None) -> str:
        payload: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": json_schema},
            }
        resp = await self._http.post("/chat/completions", json=payload)
        if resp.status_code != 200:
            raise LLMError(f"token factory {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        usage = data.get("usage") or {}
        telemetry.add(tf_calls=1, tf_tokens=usage.get("total_tokens", 0) or 0)
        return data["choices"][0]["message"]["content"]

    async def chat_json(self, model: str, messages: list[dict], schema: dict) -> dict:
        for _attempt in range(2):
            content = await self.chat(model, messages, json_schema=schema)
            try:
                parsed = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, dict):
                return parsed
        raise LLMError("model returned malformed JSON twice")

    async def list_models(self) -> list[str]:
        resp = await self._http.get("/models")
        if resp.status_code != 200:
            raise LLMError(f"token factory {resp.status_code}: {resp.text[:200]}")
        return [item["id"] for item in resp.json()["data"]]
