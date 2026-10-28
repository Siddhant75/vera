import re

_SECRET_PATTERNS = [
    ("api-key", r"sk-\w{8,}|ghp_\w{20,}|AKIA[0-9A-Z]{16}"),
    ("password", r"(?i)password\s*[=:]"),
    ("private-key", r"-----BEGIN"),
    ("card-number", r"\b\d{12,19}\b"),
]


def scan_for_secrets(text: str) -> list[str]:
    """Warn-only scan (user autonomy): pattern names found in the text."""
    found = []
    for name, pattern in _SECRET_PATTERNS:
        if re.search(pattern, text):
            found.append(name)
    return found


def _grams(text: str, n: int = 4) -> set[tuple[str, ...]]:
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def safe_query(query: str, notes: list[str], fallback: str) -> str:
    """Deterministic privacy gate: a query sharing any word-4-gram with private note
    content is blocked (returns fallback) — note text can never reach Tavily."""
    if not notes:
        return query
    note_grams = set()
    for note in notes:
        note_grams |= _grams(note)
    if _grams(query) & note_grams:
        return fallback
    return query
