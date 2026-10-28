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
    """Deterministic privacy gate. Two rules:
    - any query: word-4-gram overlap with note content -> blocked
    - short queries (<4 words) have empty 4-gram sets, so ANY distinctive token
      (>=4 chars) shared with a note blocks them too — short echoes can't slip through.
    Guarantees verbatim note text never reaches Tavily; paraphrases may evade it."""
    if not notes:
        return query
    note_grams = set()
    note_words = set()
    for note in notes:
        note_grams |= _grams(note)
        note_words |= {w for w in re.sub(r"[^\w\s]", " ", note.lower()).split() if len(w) >= 4}
    if _grams(query) & note_grams:
        return fallback
    q_words = re.sub(r"[^\w\s]", " ", query.lower()).split()
    if len(q_words) < 4 and any(w in note_words for w in q_words if len(w) >= 4):
        return fallback
    return query
