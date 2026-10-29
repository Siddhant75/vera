import httpx

from app.telemetry import telemetry

TAVILY_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"


class SearchError(Exception):
    pass


class TavilyClient:
    """Tavily search + extract client. Trust/exclusion filtering lives in the searcher stage;
    domain prefs ride inside the query (search-side personalization)."""

    ROLES = ("grounding", "prosecution", "recheck", "probe")

    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None):
        self._http = http or httpx.AsyncClient(timeout=60)
        self._api_key = api_key

    async def search(self, query: str, max_results: int = 5, role: str = "grounding",
                     topic: str | None = None, time_range: str | None = None,
                     include_domains: list[str] | None = None,
                     exclude_domains: list[str] | None = None) -> list[dict]:
        if role not in self.ROLES:
            raise ValueError(f"unknown Tavily role: {role}")
        body: dict = {"api_key": self._api_key, "query": query, "max_results": max_results}
        if topic is not None:
            body["topic"] = topic
        if time_range is not None:
            body["time_range"] = time_range
        if include_domains:
            body["include_domains"] = include_domains
            body["include_domains_mode"] = "prefer"  # boost, never restrict — post-hoc trust filter still applies
        if exclude_domains:
            body["exclude_domains"] = exclude_domains
        resp = await self._http.post(TAVILY_URL, json=body)
        if resp.status_code != 200:
            raise SearchError(f"tavily {resp.status_code}: {resp.text[:200]}")
        telemetry.add(tavily_queries=1, **{f"tavily_{role}": 1})
        return [
            {"url": r["url"], "title": r.get("title", ""), "content": r.get("content", "")}
            for r in resp.json().get("results", [])
        ]

    async def extract(self, urls: list[str], query: str | None = None,
                      extract_depth: str = "basic") -> list[dict]:
        """Full-page extraction (RAG-optimized chunks). Batch ≤20; failed URLs skipped."""
        body: dict = {"api_key": self._api_key, "urls": urls[:20], "extract_depth": extract_depth}
        if query is not None:
            body["query"] = query
        resp = await self._http.post(TAVILY_EXTRACT_URL, json=body)
        if resp.status_code != 200:
            raise SearchError(f"tavily extract {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        telemetry.add(tavily_extracts=1, tavily_queries=1)
        return [
            {"url": r["url"], "content": r.get("raw_content", "")}
            for r in data.get("results", [])
        ]
