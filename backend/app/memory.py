import json
import sqlite3
from urllib.parse import urlparse

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid TEXT,
    brief TEXT NOT NULL,
    persona TEXT NOT NULL,
    topic_key TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS verdicts (
    run_uuid TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    reason TEXT NOT NULL,
    model TEXT NOT NULL,
    web_checked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS feedback (
    run_uuid TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    helpful INTEGER NOT NULL,
    claim_text TEXT NOT NULL DEFAULT ''
);
"""

DEFAULT_PROFILE = {"persona": "engineer", "trusted_sources": [], "excluded_sources": [],
                   "role_context": "", "goals": "", "expertise_notes": ""}


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

    def set_profile(self, persona: str, trusted: list[str], excluded: list[str],
                    role_context: str = "", goals: str = "", expertise_notes: str = "") -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO profile (key, value) VALUES ('profile', ?)",
            (json.dumps({
                "persona": persona, "trusted_sources": trusted, "excluded_sources": excluded,
                "role_context": role_context, "goals": goals, "expertise_notes": expertise_notes,
            }),),
        )
        self._conn.commit()

    def save_run(self, brief: str, persona: str, topic_key: str, report: dict,
                 run_uuid: str | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO runs (run_uuid, brief, persona, topic_key, report_json) VALUES (?, ?, ?, ?, ?)",
            (run_uuid, brief, persona, topic_key, json.dumps(report)),
        )
        self._conn.commit()
        return cur.lastrowid

    def save_verdicts(self, run_uuid: str, verdicts: list[dict]) -> None:
        self._conn.executemany(
            "INSERT INTO verdicts (run_uuid, claim_id, verdict, reason, model, web_checked) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (run_uuid, v["claim_id"], v["verdict"], v["reason"], v["model"], int(v.get("web_checked", False)))
                for v in verdicts
            ],
        )
        self._conn.commit()

    def _report_row(self, row) -> dict | None:
        return json.loads(row[0]) if row else None

    def last_report_for_topic(self, topic_key: str) -> dict | None:
        exact = self._conn.execute(
            "SELECT report_json FROM runs WHERE topic_key = ? ORDER BY id DESC LIMIT 1",
            (topic_key,),
        ).fetchone()
        if exact:
            return self._report_row(exact)
        # fuzzy: same research phrased differently still hits memory (delta across wordings)
        from difflib import SequenceMatcher
        keys = [r[0] for r in self._conn.execute("SELECT DISTINCT topic_key FROM runs").fetchall()]
        tokens = set(topic_key.replace("-", " ").split())
        best, best_score = None, 0.0
        for k in keys:
            score = max(SequenceMatcher(None, topic_key, k).ratio(),
                        len(tokens & set(k.replace("-", " ").split())) / max(len(tokens), 1))
            if score > best_score:
                best, best_score = k, score
        if best_score >= 0.75 and best:
            row = self._conn.execute(
                "SELECT report_json FROM runs WHERE topic_key = ? ORDER BY id DESC LIMIT 1",
                (best,),
            ).fetchone()
            return self._report_row(row)
        return None

    def get_report(self, run_uuid: str) -> dict | None:
        row = self._conn.execute(
            "SELECT report_json FROM runs WHERE run_uuid = ?", (str(run_uuid),)
        ).fetchone()
        return self._report_row(row)

    def add_feedback(self, run_uuid: str, claim_id: str, helpful: bool,
                     claim_text: str = "") -> None:
        self._conn.execute(
            "INSERT INTO feedback (run_uuid, claim_id, helpful, claim_text) VALUES (?, ?, ?, ?)",
            (str(run_uuid), claim_id, int(helpful), claim_text),
        )
        self._conn.commit()

    def negative_claim_texts(self, limit: int = 10) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT claim_text FROM feedback WHERE helpful = 0 AND claim_text != '' "
            "ORDER BY rowid DESC LIMIT ?", (limit,),
        ).fetchall()
        return [r[0] for r in rows]

    def feedback_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]

    def prior_artifacts_for_topic(self, topic_key: str) -> dict | None:
        """Latest run's sections + verdicts for a topic — the reuse payload for delta runs."""
        row = self._conn.execute(
            "SELECT run_uuid, report_json FROM runs WHERE topic_key = ? ORDER BY id DESC LIMIT 1",
            (topic_key,),
        ).fetchone()
        if not row:
            return None
        run_uuid, report_json = row
        report = json.loads(report_json)
        verdicts = {
            r[0]: {"verdict": r[1], "reason": r[2], "model": r[3], "web_checked": bool(r[4])}
            for r in self._conn.execute(
                "SELECT claim_id, verdict, reason, model, web_checked FROM verdicts WHERE run_uuid = ?",
                (run_uuid,),
            ).fetchall()
        }
        return {"sections": report.get("sections", []), "verdicts": verdicts}

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
