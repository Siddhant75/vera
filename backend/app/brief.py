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
