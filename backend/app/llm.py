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

    async def chat(self, model: str, messages: list[dict], max_tokens: int = 2000) -> str:
        import asyncio

        payload: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
        resp = None
        for attempt in range(3):  # 529/503 = transient platform overload: back off, don't die
            resp = await self._http.post("/chat/completions", json=payload)
            if resp.status_code in (529, 503) and attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            break
        if resp.status_code != 200:
            raise LLMError(f"token factory {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        usage = data.get("usage") or {}
        telemetry.add(tf_calls=1, tf_tokens=usage.get("total_tokens", 0) or 0)
        return data["choices"][0]["message"]["content"] or ""

    async def chat_json(self, model: str, messages: list[dict], schema: dict,
                        max_tokens: int = 4096) -> dict:
        # No response_format json_schema: it garbles output on some Token Factory reasoning
        # models (Nemotron-3 family). Schema goes into the prompt; braces extracted from prose.
        schema_note = {
            "role": "system",
            "content": f"Respond with ONLY JSON matching this schema: {json.dumps(schema)}",
        }
        messages = [*messages, schema_note]
        for _attempt in range(3):
            content = await self.chat(model, messages, max_tokens=max_tokens)
            try:
                start, end = content.find("{"), content.rfind("}")
                if start == -1 or end <= start:
                    raise json.JSONDecodeError("no object", content, 0)
                parsed = json.loads(content[start:end + 1])
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, dict):
                return parsed
        raise LLMError("model returned malformed JSON three times")

    async def list_models(self) -> list[str]:
        resp = await self._http.get("/models")
        if resp.status_code != 200:
            raise LLMError(f"token factory {resp.status_code}: {resp.text[:200]}")
        return [item["id"] for item in resp.json()["data"]]
