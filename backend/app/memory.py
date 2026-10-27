import json
import sqlite3
from urllib.parse import urlparse

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brief TEXT NOT NULL,
    persona TEXT NOT NULL,
    topic_key TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS verdicts (
    run_id INTEGER NOT NULL,
    claim_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    reason TEXT NOT NULL,
    model TEXT NOT NULL,
    web_checked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS feedback (
    run_id INTEGER NOT NULL,
    claim_id TEXT NOT NULL,
    helpful INTEGER NOT NULL
);
"""

DEFAULT_PROFILE = {"persona": "engineer", "trusted_sources": [], "excluded_sources": []}


class Memory:
    """SQLite persistence: profile, runs, verdicts, feedback. Sync on purpose (hackathon scope)."""

    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def get_profile(self) -> dict:
        row = self._conn.execute("SELECT value FROM profile WHERE key='profile'").fetchone()
        if row is None:
            return dict(DEFAULT_PROFILE)
        return json.loads(row[0])

    def set_profile(self, persona: str, trusted: list[str], excluded: list[str]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO profile (key, value) VALUES ('profile', ?)",
            (json.dumps({"persona": persona, "trusted_sources": trusted, "excluded_sources": excluded}),),
        )
        self._conn.commit()

    def save_run(self, brief: str, persona: str, topic_key: str, report: dict) -> int:
        cur = self._conn.execute(
            "INSERT INTO runs (brief, persona, topic_key, report_json) VALUES (?, ?, ?, ?)",
            (brief, persona, topic_key, json.dumps(report)),
        )
        self._conn.commit()
        return cur.lastrowid

    def save_verdicts(self, run_id: int, verdicts: list[dict]) -> None:
        self._conn.executemany(
            "INSERT INTO verdicts (run_id, claim_id, verdict, reason, model, web_checked) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (run_id, v["claim_id"], v["verdict"], v["reason"], v["model"], int(v.get("web_checked", False)))
                for v in verdicts
            ],
        )
        self._conn.commit()

    def _report_row(self, row) -> dict | None:
        return json.loads(row[0]) if row else None

    def last_report_for_topic(self, topic_key: str) -> dict | None:
        row = self._conn.execute(
            "SELECT report_json FROM runs WHERE topic_key = ? ORDER BY id DESC LIMIT 1",
            (topic_key,),
        ).fetchone()
        return self._report_row(row)

    def get_report(self, run_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT report_json FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        return self._report_row(row)

    def add_feedback(self, run_id: int, claim_id: str, helpful: bool) -> None:
        self._conn.execute(
            "INSERT INTO feedback (run_id, claim_id, helpful) VALUES (?, ?, ?)",
            (run_id, claim_id, int(helpful)),
        )
        self._conn.commit()

    def feedback_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]

    def trust_multiplier(self, domain: str) -> float:
        if not domain:
            return 1.0
        excluded = self.get_profile().get("excluded_sources", [])
        for item in excluded:
            if item in domain or domain in item:
                return 0.0
        return 1.0


def domain_of(url: str) -> str:
    return urlparse(url).hostname or ""
