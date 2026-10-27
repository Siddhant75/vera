from app.brief import parse_requirements


class SearchBudget:
    """Deterministic per-run Tavily search cap. Code owns the counter, not the LLM."""

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def try_consume(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


def budget_for_brief(brief: str) -> int:
    reqs = parse_requirements(brief)
    return min(12 + 2 * len(reqs), 40) if reqs else 20
