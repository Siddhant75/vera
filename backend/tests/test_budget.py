from app.brief import parse_requirements
from app.budget import SearchBudget, budget_for_brief


def test_try_consume_exhausts():
    b = SearchBudget(2)
    assert b.try_consume() and b.try_consume()
    assert not b.try_consume()
    assert b.used == 2


def test_budget_for_brief_scales_with_requirements():
    prose = "Should we adopt Kubernetes?"
    assert budget_for_brief(prose) == 20
    reqs = "Brief\n- a\n- b\n- c"
    assert budget_for_brief(reqs) == min(12 + 2 * len(parse_requirements(reqs)), 40)  # 18
    heavy = "\n".join(f"- req {i}" for i in range(30))
    assert budget_for_brief(heavy) == 36  # parser caps at 12 requirements → 12+2×12
