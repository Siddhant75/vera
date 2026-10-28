import httpx

from app.telemetry import telemetry

TAVILY_URL = "https://api.tavily.com/search"


class SearchError(Exception):
    pass


class TavilyClient:
    """Tavily search client. Trust/exclusion filtering lives in the searcher stage."""

    ROLES = ("grounding", "prosecution", "recheck")

    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None):
        self._http = http or httpx.AsyncClient(timeout=60)
        self._api_key = api_key

    async def search(self, query: str, max_results: int = 5, role: str = "grounding") -> list[dict]:
        if role not in self.ROLES:
            raise ValueError(f"unknown Tavily role: {role}")
        resp = await self._http.post(
            TAVILY_URL,
            json={"api_key": self._api_key, "query": query, "max_results": max_results},
        )
        if resp.status_code != 200:
            raise SearchError(f"tavily {resp.status_code}: {resp.text[:200]}")
        telemetry.add(tavily_queries=1, **{f"tavily_{role}": 1})
        return [
            {"url": r["url"], "title": r.get("title", ""), "content": r.get("content", "")}
            for r in resp.json().get("results", [])
        ]
