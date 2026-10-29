from app.memory import Memory

REPORT = {"brief": "b", "persona": "engineer", "topic_key": "k", "sections": []}


def test_default_profile(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    assert m.get_profile() == {"persona": "engineer", "trusted_sources": [], "excluded_sources": [],
                            "role_context": "", "goals": "", "expertise_notes": ""}


def test_profile_round_trip(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.set_profile("founder", ["a.com"], ["b.com"])
    p = m.get_profile()
    assert (p["persona"], p["trusted_sources"], p["excluded_sources"]) == ("founder", ["a.com"], ["b.com"])
    assert p["role_context"] == ""


def test_save_run_and_last_report(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    run_id = m.save_run("brief", "engineer", "k", REPORT)
    assert isinstance(run_id, int)
    assert m.last_report_for_topic("k") == REPORT
    assert m.last_report_for_topic("unknown") is None


def test_save_run_source_roundtrip(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.save_run("b", "engineer", "k", REPORT, run_uuid="r1", source="watch")
    m.save_run("b", "engineer", "k", REPORT, run_uuid="r2")  # no source → manual
    sources = {r["run_uuid"]: r["source"] for r in m.list_runs()}
    assert sources["r1"] == "watch"
    assert sources["r2"] == "manual"


def test_runs_source_migrates_legacy(tmp_path):
    import sqlite3
    p = str(tmp_path / "legacy.db")
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, run_uuid TEXT, brief TEXT NOT NULL, "
              "persona TEXT NOT NULL, topic_key TEXT NOT NULL, report_json TEXT NOT NULL, "
              "created_at TEXT NOT NULL DEFAULT (datetime('now')))")
    c.commit()
    c.close()
    m = Memory(p)
    m.save_run("b", "engineer", "k", REPORT, run_uuid="r1")
    assert m.list_runs()[0]["source"] == "manual"


def test_update_watch_partial(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    wid = m.add_watch("k8s choice", "old brief", "founder", interval_hours=6)
    m.update_watch(wid, brief="new brief", interval_hours=12)
    w = m.list_watches()[0]
    assert w["brief"] == "new brief"
    assert w["interval_hours"] == 12
    assert w["topic"] == "k8s choice"  # untouched
    assert w["persona"] == "founder"   # untouched
    m.update_watch(wid, interval_hours=0)
    assert m.list_watches()[0]["interval_hours"] == 1  # re-clamped


def test_update_watch_missing_fields_kept(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    wid = m.add_watch("t", "b", "founder", interval_hours=6)
    m.update_watch(wid)
    w = m.list_watches()[0]
    assert (w["topic"], w["brief"], w["persona"], w["interval_hours"]) == ("t", "b", "founder", 6)


def test_last_report_most_recent_wins(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.save_run("brief1", "engineer", "k", {"v": 1})
    m.save_run("brief2", "founder", "k", {"v": 2})
    assert m.last_report_for_topic("k") == {"v": 2}


def test_get_report(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.save_run("brief", "engineer", "k", REPORT, run_uuid="r1")
    assert m.get_report("r1") == REPORT
    assert m.get_report("nope") is None


def test_trust_multiplier(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.set_profile("engineer", [], ["excluded.com"])
    assert m.trust_multiplier("excluded.com") == 0.0
    assert m.trust_multiplier("other.com") == 1.0


def test_add_feedback_saves_row(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.save_run("brief", "engineer", "k", REPORT, run_uuid="r1")
    m.save_verdicts("r1", [{"claim_id": "c1", "verdict": "supported", "reason": "r", "model": "m"}])
    m.add_feedback("r1", "c1", False)
    assert m.feedback_count() == 1


def test_profile_extended_fields(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.set_profile("founder", ["a.com"], ["b.com"],
                  role_context="CTO of a 10-person startup", goals="ship ML API cheaply",
                  expertise_notes="knows Docker, new to k8s")
    p = m.get_profile()
    assert p["role_context"] == "CTO of a 10-person startup"
    assert p["goals"] == "ship ML API cheaply"
    assert p["expertise_notes"] == "knows Docker, new to k8s"


def test_negative_feedback_texts_retrievable(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.save_run("brief", "engineer", "k", REPORT, run_uuid="r1")
    m.add_feedback("r1", "c1", False, claim_text="K8s is always cheaper")
    m.add_feedback("r1", "c2", True, claim_text="serverless is best")
    assert m.negative_claim_texts() == ["K8s is always cheaper"]


def test_last_report_fuzzy_topic(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.save_run("brief1", "engineer", "kubernetes-vs-serverless", REPORT, run_uuid="r1")
    out = m.last_report_for_topic("kubernetes or serverless")
    assert out == REPORT
    assert m.last_report_for_topic("completely unrelated topic") is None


def test_prior_artifacts_for_topic(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    report = {"sections": [{"sub_question": "What is X?", "narrative": "n",
                            "claims": [{"id": "c1", "text": "prior claim", "citation_urls": ["https://old.com/1"]}]}]}
    m.save_run("brief", "engineer", "k", report, run_uuid="r1")
    m.save_verdicts("r1", [{"claim_id": "c1", "verdict": "supported", "reason": "ok", "model": "m"}])
    art = m.prior_artifacts_for_topic("k")
    assert art["sections"][0]["claims"][0]["id"] == "c1"
    assert art["verdicts"]["c1"]["verdict"] == "supported"
    assert m.prior_artifacts_for_topic("missing") is None


def test_feedback_claim_text_migrates_legacy(tmp_path):
    import sqlite3
    p = str(tmp_path / "legacy.db")
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE feedback (run_uuid TEXT NOT NULL, claim_id TEXT NOT NULL, helpful INTEGER NOT NULL)")
    c.commit()
    c.close()
    m = Memory(p)
    m.add_feedback("r1", "c1", helpful=False, claim_text="bad claim")
    assert m.negative_claim_texts() == ["bad claim"]
