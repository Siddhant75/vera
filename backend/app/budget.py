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


_TIER_BUDGET = {"quick": 8, "standard": 14, "deep": 20}


def budget_for_brief(brief: str, depth: str = "standard") -> int:
    reqs = parse_requirements(brief)
    if reqs:  # explicit requirements: formula wins, tier irrelevant (quick is clamped to standard+)
        return min(12 + 2 * len(reqs), 40)
    return _TIER_BUDGET.get(depth, 14)
