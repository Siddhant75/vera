import pytest

from app.memory import Memory

REPORT = {"sections": [{"sub_question": "q", "narrative": "n", "claims": []}], "open_questions": []}


def test_list_runs_and_delete_run(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    m.save_run("brief1", "engineer", "k1", REPORT, run_uuid="r1")
    m.save_verdicts("r1", [{"claim_id": "c1", "verdict": "supported", "reason": "r", "model": "m"}])
    m.save_sources("r1", [{"url": "https://a.com/1", "title": "A"}])
    m.save_run("brief2", "founder", "k2", REPORT, run_uuid="r2")
    runs = m.list_runs()
    assert len(runs) == 2
    assert {r["run_uuid"] for r in runs} == {"r1", "r2"}
    m.delete_run("r1")
    runs = m.list_runs()
    assert {r["run_uuid"] for r in runs} == {"r2"}
    assert m.get_report("r1") is None
    assert m.get_sources("r1") == []


def test_purge_all_wipes_everything(tmp_path):
    from app.memory import DEFAULT_PROFILE
    m = Memory(str(tmp_path / "t.db"))
    m.set_profile("founder", [], [])
    m.save_run("b", "founder", "k", REPORT, run_uuid="r1")
    m.save_verdicts("r1", [{"claim_id": "c", "verdict": "supported", "reason": "r", "model": "m"}])
    m.save_sources("r1", [{"url": "u", "title": "t"}])
    m.add_watch("t", "b", "founder")
    m.add_note("k", "note")
    m.upsert_skill("s", "founder", "b", "k")
    m.purge_all()
    assert m.list_runs() == []
    assert m.list_watches() == []
    assert m.list_notes("k") == []
    assert m.list_skills() == []
    assert m.get_profile() == DEFAULT_PROFILE  # profile also wiped, back to defaults
    assert m.get_report("r1") is None


async def test_check_due_watches_empty_list_noop(tmp_path):
    from app.watcher import check_due_watches
    from conftest import FakeLLM, FakeTavily

    m = Memory(str(tmp_path / "t.db"))
    llm = FakeLLM()

    async def boom(*a, **k):
        raise AssertionError("no Tavily calls expected")

    async def noop(e):
        pass

    await check_due_watches(m, llm, type("T", (), {"search": boom})(), emit=noop)
    assert m.list_watches() == []
