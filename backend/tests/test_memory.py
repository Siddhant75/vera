from app.memory import Memory

REPORT = {"brief": "b", "persona": "engineer", "topic_key": "k", "sections": []}


def test_default_profile(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    assert m.get_profile() == {"persona": "engineer", "trusted_sources": [], "excluded_sources": []}


def test_profile_round_trip(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.set_profile("founder", ["a.com"], ["b.com"])
    assert m.get_profile() == {"persona": "founder", "trusted_sources": ["a.com"], "excluded_sources": ["b.com"]}


def test_save_run_and_last_report(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    run_id = m.save_run("brief", "engineer", "k", REPORT)
    assert isinstance(run_id, int)
    assert m.last_report_for_topic("k") == REPORT
    assert m.last_report_for_topic("unknown") is None


def test_last_report_most_recent_wins(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.save_run("brief1", "engineer", "k", {"v": 1})
    m.save_run("brief2", "founder", "k", {"v": 2})
    assert m.last_report_for_topic("k") == {"v": 2}


def test_get_report(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    run_id = m.save_run("brief", "engineer", "k", REPORT)
    assert m.get_report(run_id) == REPORT
    assert m.get_report(999) is None


def test_trust_multiplier(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.set_profile("engineer", [], ["excluded.com"])
    assert m.trust_multiplier("excluded.com") == 0.0
    assert m.trust_multiplier("other.com") == 1.0


def test_add_feedback_saves_row(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    run_id = m.save_run("brief", "engineer", "k", REPORT)
    m.save_verdicts(run_id, [{"claim_id": "c1", "verdict": "supported", "reason": "r", "model": "m"}])
    m.add_feedback(run_id, "c1", False)
    assert m.feedback_count() == 1
