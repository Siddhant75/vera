from app.brief import parse_requirements


def test_bullets_extracted():
    brief = "Compare k8s vs serverless.\n- cost analysis\n- cold start behavior\n* team expertise"
    assert parse_requirements(brief) == ["cost analysis", "cold start behavior", "team expertise"]


def test_numbered_extracted():
    brief = "Research this:\n1. latency targets\n2) pricing models"
    assert parse_requirements(brief) == ["latency targets", "pricing models"]


def test_dedupe_case_insensitive():
    brief = "- Cost analysis\n- cost analysis\n- COST ANALYSIS"
    assert parse_requirements(brief) == ["Cost analysis"]


def test_prose_brief_no_requirements():
    assert parse_requirements("Should we adopt Kubernetes or serverless?") == []


def test_max_twelve():
    brief = "\n".join(f"- req {i}" for i in range(20))
    assert len(parse_requirements(brief)) == 12


def test_strips_sub_point_indentation():
    brief = "- top\n  - sub point"
    assert parse_requirements(brief) == ["top", "sub point"]
