import re
from datetime import datetime


class SafeDict(dict):
    """Unknown {var} stays literal — template never blocks a run."""

    def __missing__(self, key):
        return "{" + key + "}"


def fill_template(template: str, user_vars: dict, auto_vars: dict) -> str:
    merged = {**auto_vars, **user_vars}  # user vars override autos
    try:
        return template.format_map(SafeDict(**merged))
    except (ValueError, IndexError):  # braces without valid fields ({}, {0}, lone {) — regex path
        return re.sub(r"\{(\w+)\}",
                      lambda m: str(merged.get(m.group(1), "{" + m.group(1) + "}")),
                      template)


def auto_vars(topic: str) -> dict:
    today = datetime.now()
    return {"topic": topic, "date": today.strftime("%Y-%m-%d"),
            "quarter": f"Q{(today.month - 1) // 3 + 1}-{today.year}"}
