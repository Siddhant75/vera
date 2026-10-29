import re

_REQ_LINE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+)$")


def parse_requirements(brief: str) -> list[str]:
    """Bullet/numbered lines from a structured brief, deterministically. Prose → []."""
    out, seen = [], set()
    for line in brief.splitlines():
        m = _REQ_LINE.match(line)
        if not m:
            continue
        req = m.group(1).strip()
        key = req.lower()
        if req and key not in seen:
            seen.add(key)
            out.append(req)
        if len(out) >= 12:
            break
    return out


def clamp_depth(depth: str, brief: str) -> str:
    """Code owns the depth decision: the planner's classification is advisory.
    Unknown/missing -> standard; >=3 explicit bullets can never be quick."""
    if depth not in ("quick", "standard", "deep"):
        depth = "standard"
    if len(parse_requirements(brief)) >= 3 and depth == "quick":
        depth = "standard"
    return depth
