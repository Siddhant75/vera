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
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_key TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    brief TEXT NOT NULL,
    persona TEXT NOT NULL,
    interval_hours INTEGER NOT NULL,
    last_checked TEXT,
    last_run_uuid TEXT,
    last_status TEXT,
    last_changes INTEGER
);
CREATE TABLE IF NOT EXISTS skills (
    name TEXT PRIMARY KEY,
    persona TEXT NOT NULL,
    brief_template TEXT NOT NULL,
    topic TEXT NOT NULL,
    trusted_sources TEXT NOT NULL DEFAULT '',
    excluded_sources TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sources (
    run_uuid TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL
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
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(watches)").fetchall()]
        if "last_digest" not in cols:  # legacy DBs: migrate in place
            self._conn.execute("ALTER TABLE watches ADD COLUMN last_digest TEXT")
        if "error_count" not in cols:
            self._conn.execute("ALTER TABLE watches ADD COLUMN error_count INTEGER NOT NULL DEFAULT 0")
        rcols = [r[1] for r in self._conn.execute("PRAGMA table_info(runs)").fetchall()]
        if "source" not in rcols:
            self._conn.execute("ALTER TABLE runs ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
        fcols = [r[1] for r in self._conn.execute("PRAGMA table_info(feedback)").fetchall()]
        if "claim_text" not in fcols:
            self._conn.execute("ALTER TABLE feedback ADD COLUMN claim_text TEXT NOT NULL DEFAULT ''")

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
                 run_uuid: str | None = None, source: str = "manual") -> int:
        cur = self._conn.execute(
            "INSERT INTO runs (run_uuid, brief, persona, topic_key, report_json, source) VALUES (?, ?, ?, ?, ?, ?)",
            (run_uuid, brief, persona, topic_key, json.dumps(report), source),
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

    def add_note(self, topic_key: str, content: str) -> tuple[int, list[str]]:
        from app.privacy import scan_for_secrets
        warnings = scan_for_secrets(content)
        stored = content[:10_000]
        # cap 5 per topic: evict oldest
        old = self._conn.execute("SELECT id FROM notes WHERE topic_key = ? ORDER BY id", (topic_key,)).fetchall()
        if len(old) >= 5:
            for (oid,) in old[:len(old) - 4]:
                self._conn.execute("DELETE FROM notes WHERE id = ?", (oid,))
        cur = self._conn.execute("INSERT INTO notes (topic_key, content) VALUES (?, ?)",
                                 (topic_key, stored))
        self._conn.commit()
        return cur.lastrowid, warnings

    def list_notes(self, topic_key: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, content, created_at FROM notes WHERE topic_key = ? ORDER BY id DESC LIMIT 5",
            (topic_key,),
        ).fetchall()
        return [{"id": r[0], "content": r[1], "created_at": r[2]} for r in rows]

    def delete_note(self, note_id: int) -> None:
        self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self._conn.commit()

    def add_watch(self, topic: str, brief: str, persona: str, interval_hours: int = 6) -> int:
        interval = max(1, int(interval_hours or 0))  # never a busy-loop
        cur = self._conn.execute(
            "INSERT INTO watches (topic, brief, persona, interval_hours) VALUES (?, ?, ?, ?)",
            (topic, brief, persona, interval),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_watch(self, watch_id: int, topic: str | None = None, brief: str | None = None,
                     persona: str | None = None, interval_hours: int | None = None) -> bool:
        """Partial re-freeze: None = keep. Interval re-clamped >=1. False = unknown id."""
        if not self._conn.execute("SELECT 1 FROM watches WHERE id = ?", (watch_id,)).fetchone():
            return False
        interval = max(1, int(interval_hours)) if interval_hours is not None else None
        self._conn.execute(
            "UPDATE watches SET topic = COALESCE(?, topic), brief = COALESCE(?, brief), "
            "persona = COALESCE(?, persona), interval_hours = COALESCE(?, interval_hours) WHERE id = ?",
            (topic, brief, persona, interval, watch_id),
        )
        self._conn.commit()
        return True

    def remove_watch(self, watch_id: int) -> None:
        self._conn.execute("DELETE FROM watches WHERE id = ?", (watch_id,))
        self._conn.commit()

    def list_watches(self) -> list[dict]:
        rows = self._conn.execute("SELECT id, topic, brief, persona, interval_hours, last_checked, last_run_uuid, last_status, last_changes, last_digest, error_count FROM watches ORDER BY id").fetchall()
        return [{"id": r[0], "topic": r[1], "brief": r[2], "persona": r[3], "interval_hours": r[4],
                 "last_checked": r[5], "last_run_uuid": r[6], "last_status": r[7], "last_changes": r[8],
                 "last_digest": r[9], "error_count": r[10] or 0}
                for r in rows]

    def set_watch_result(self, watch_id: int, status: str, run_uuid: str | None = None,
                         changes: int | None = None, checked_at: str | None = None,
                         digest: str | None = None) -> None:
        from datetime import datetime, timezone
        ts = checked_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._conn.execute(
            "UPDATE watches SET last_status = ?, last_run_uuid = COALESCE(?, last_run_uuid), "
            "last_changes = COALESCE(?, last_changes), last_digest = COALESCE(?, last_digest), "
            "error_count = CASE WHEN ? = 'error' THEN COALESCE(error_count, 0) + 1 ELSE 0 END, "
            "last_checked = ? WHERE id = ?",
            (status, run_uuid, changes, digest, status, ts, watch_id),
        )
        self._conn.commit()

    def upsert_skill(self, name: str, persona: str, brief_template: str, topic: str,
                     trusted: list[str] | None = None, excluded: list[str] | None = None) -> int:
        self._conn.execute(
            "INSERT OR REPLACE INTO skills (name, persona, brief_template, topic, trusted_sources, excluded_sources) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, persona, brief_template, topic,
             ",".join(trusted or []), ",".join(excluded or [])),
        )
        self._conn.commit()
        return self._conn.execute("SELECT rowid FROM skills WHERE name = ?", (name,)).fetchone()[0]

    def list_skills(self) -> list[dict]:
        rows = self._conn.execute("SELECT name, persona, brief_template, topic, trusted_sources, excluded_sources FROM skills ORDER BY name").fetchall()
        return [{"name": r[0], "persona": r[1], "brief_template": r[2], "topic": r[3],
                 "trusted_sources": [x for x in r[4].split(",") if x],
                 "excluded_sources": [x for x in r[5].split(",") if x]} for r in rows]

    def delete_skill(self, name: str) -> None:
        self._conn.execute("DELETE FROM skills WHERE name = ?", (name,))
        self._conn.commit()

    def list_runs(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT run_uuid, brief, persona, topic_key, created_at, source FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{"run_uuid": r[0], "brief": r[1], "persona": r[2], "topic_key": r[3], "created_at": r[4],
                 "source": r[5]}
                for r in rows]

    def delete_run(self, run_uuid: str) -> None:
        for table in ("runs", "verdicts", "sources", "feedback"):
            col = "run_uuid"
            self._conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (str(run_uuid),))
        self._conn.commit()

    def purge_all(self) -> None:
        for table in ("runs", "verdicts", "sources", "feedback", "watches", "notes", "skills", "profile"):
            self._conn.execute(f"DELETE FROM {table}")
        self._conn.commit()

    def latest_run_uuid_for_topic(self, topic_key: str) -> str | None:
        row = self._conn.execute(
            "SELECT run_uuid FROM runs WHERE topic_key = ? ORDER BY id DESC LIMIT 1", (topic_key,)
        ).fetchone()
        return row[0] if row else None

    def save_sources(self, run_uuid: str, sources: list[dict]) -> None:
        self._conn.executemany(
            "INSERT INTO sources (run_uuid, url, title) VALUES (?, ?, ?)",
            [(str(run_uuid), s["url"], s.get("title", "")) for s in sources],
        )
        self._conn.commit()

    def get_sources(self, run_uuid: str) -> list[dict]:
        return [{"url": r[0], "title": r[1]} for r in self._conn.execute(
            "SELECT url, title FROM sources WHERE run_uuid = ?", (str(run_uuid),)
        ).fetchall()]

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


def clean_domains(domains: list[str]) -> list[str]:
    """Normalize user-supplied domain prefs (accept bare domains or URLs), dedupe, cap 150 (Tavily limit)."""
    out: list[str] = []
    for d in domains or []:
        d = (d or "").strip().lower()
        if not d:
            continue
        if "." in d and "/" in d:  # looks like a URL — keep the host
            d = urlparse(d).hostname or d
        if d and d not in out:
            out.append(d)
    return out[:150]
