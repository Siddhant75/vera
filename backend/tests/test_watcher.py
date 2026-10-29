import asyncio

import pytest

from conftest import FakeLLM, FakeTavily

from app.memory import Memory
from app.watcher import check_due_watches, probe_changed


@pytest.fixture
def memory(tmp_path):
    return Memory(str(tmp_path / "t.db"))


def test_add_watch_defaults_and_clamp(memory):
    wid = memory.add_watch("k8s choice", "Brief here", "founder", interval_hours=0)
    watches = memory.list_watches()
    assert len(watches) == 1
    assert watches[0]["interval_hours"] == 1  # clamped from 0
    assert watches[0]["last_status"] is None


def test_remove_watch(memory):
    wid = memory.add_watch("t", "b", "founder")
    memory.remove_watch(wid)
    assert memory.list_watches() == []


async def test_probe_changed_new_url(memory, tmp_path):
    memory.add_watch("k8s choice", "Brief", "founder")
    memory.save_run("Brief", "founder", "k8s-choice", {"sections": []}, run_uuid="old1")
    memory.save_sources("old1", [{"url": "https://known.com/a", "title": "A"}])
    tavily = FakeTavily({"k8s choice": [{"url": "https://known.com/a", "title": "A", "content": "c"},
                                        {"url": "https://fresh.com/b", "title": "B", "content": "c"}]})
    watch = memory.list_watches()[0]
    assert await probe_changed(memory, tavily, watch) is True


async def test_probe_changed_no_new_urls(memory):
    memory.add_watch("k8s choice", "Brief", "founder")
    memory.save_run("Brief", "founder", "k8s-choice", {"sections": []}, run_uuid="old1")
    memory.save_sources("old1", [{"url": "https://known.com/a", "title": "A"}])
    tavily = FakeTavily({"k8s choice": [{"url": "https://known.com/a", "title": "A", "content": "c"}]})
    watch = memory.list_watches()[0]
    assert await probe_changed(memory, tavily, watch) is False


async def test_probe_ignores_excluded_domains(memory):
    memory.add_watch("k8s choice", "Brief", "founder")
    memory.save_run("Brief", "founder", "k8s-choice", {"sections": []}, run_uuid="old1")
    memory.save_sources("old1", [{"url": "https://known.com/a", "title": "A"}])
    memory.set_profile("engineer", [], ["excluded.com"])
    tavily = FakeTavily({"k8s choice": [{"url": "https://excluded.com/x", "title": "X", "content": "c"}]})
    watch = memory.list_watches()[0]
    assert await probe_changed(memory, tavily, watch) is False  # banned-domain news is not news


async def test_probe_change_on_allowed_domain_still_fires(memory):
    memory.add_watch("k8s choice", "Brief", "founder")
    memory.save_run("Brief", "founder", "k8s-choice", {"sections": []}, run_uuid="old1")
    memory.save_sources("old1", [{"url": "https://known.com/a", "title": "A"}])
    memory.set_profile("engineer", [], ["excluded.com"])
    tavily = FakeTavily({"k8s choice": [
        {"url": "https://excluded.com/x", "title": "X", "content": "c"},
        {"url": "https://fresh.com/b", "title": "B", "content": "c"}]})
    watch = memory.list_watches()[0]
    assert await probe_changed(memory, tavily, watch) is True


async def test_first_watch_no_history_runs(memory):
    memory.add_watch("k8s choice", "Brief", "founder")
    tavily = FakeTavily()
    watch = memory.list_watches()[0]
    assert await probe_changed(memory, tavily, watch) is True


async def test_due_watch_triggers_delta_and_digest(memory):
    memory.add_watch("Explain X", "Explain X", "engineer", interval_hours=1)
    # seed a prior run so probe sees "changed" via new URL
    memory.save_run("Explain X", "engineer", "explain-x", {"sections": []}, run_uuid="old1")
    memory.save_sources("old1", [{"url": "https://known.com/a", "title": "A"}])

    PLAN = {"sub_questions": [{"id": "a", "text": "What is X?"}]}
    DRAFT = {"claims": [{"text": "X changed", "citation_urls": ["https://fresh.com/z"]}]}
    VER = {"verdict": "supported", "reason": "r"}
    NARR = {"narrative": "n", "open_questions": []}
    llm = FakeLLM([PLAN, DRAFT, VER, VER, NARR], planner_model="m-p", verifier_models=["m-v"])
    tavily = FakeTavily({"Explain X": [{"url": "https://fresh.com/z", "title": "Z", "content": "c"}]})

    async def noop_emit(e):
        pass

    await check_due_watches(memory, llm, tavily, emit=noop_emit)
    w = memory.list_watches()[0]
    assert w["last_status"] == "changed"
    assert w["last_run_uuid"] and w["last_run_uuid"] != "old1"
    assert "Explain X" in (w["last_digest"] or "")


def test_watch_digest_roundtrip(memory):
    wid = memory.add_watch("k8s", "brief", "engineer")
    memory.set_watch_result(wid, "changed", run_uuid="r1", changes=2,
                            digest="Vera update on 'k8s': 2 changes - X; Y")
    assert memory.list_watches()[0]["last_digest"] == "Vera update on 'k8s': 2 changes - X; Y"


def test_memory_migrates_legacy_watches_table(tmp_path):
    import sqlite3
    p = str(tmp_path / "legacy.db")
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE watches (id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT, brief TEXT, "
              "persona TEXT, interval_hours INTEGER, last_checked TEXT, last_run_uuid TEXT, "
              "last_status TEXT, last_changes INTEGER)")
    c.execute("INSERT INTO watches (topic, brief, persona, interval_hours) VALUES ('t','b','e',6)")
    c.commit()
    c.close()
    m = Memory(p)
    m.set_watch_result(1, "changed", digest="d")
    assert m.list_watches()[0]["last_digest"] == "d"


async def test_no_change_skips_llm(memory):
    memory.add_watch("Explain X", "Explain X", "engineer")
    memory.save_run("Explain X", "engineer", "explain-x", {"sections": []}, run_uuid="old1")
    memory.save_sources("old1", [{"url": "https://known.com/a", "title": "A"}])
    tavily = FakeTavily({"Explain X": [{"url": "https://known.com/a", "title": "A", "content": "c"}]})
    llm = FakeLLM()  # no responses queued: any LLM call would raise

    async def noop_emit(e):
        pass

    await check_due_watches(memory, llm, tavily, emit=noop_emit)
    assert memory.list_watches()[0]["last_status"] == "no-change"
    assert llm.prompts == []


async def test_one_bad_watch_others_still_probed(memory):
    memory.add_watch("boom topic", "b1", "engineer")
    memory.add_watch("good topic", "b2", "engineer")
    calls = []

    async def probe(memory_, tavily_, watch):
        calls.append(watch["topic"])
        if watch["topic"] == "boom topic":
            raise RuntimeError("probe exploded")
        return False

    import app.watcher as W
    llm = FakeLLM()

    async def noop_emit(e):
        pass

    await W.check_due_watches(memory, llm, FakeTavily(), emit=noop_emit, probe_fn=probe)
    assert calls == ["boom topic", "good topic"]  # second watch still processed
    statuses = {w["topic"]: w["last_status"] for w in memory.list_watches()}
    assert statuses["boom topic"] == "error"
    assert statuses["good topic"] == "no-change"


async def test_budget_exhausted_marks_budget_limited(memory, monkeypatch):
    from app import telemetry
    telemetry.telemetry.add(tf_tokens=10_000_000)  # way over any budget
    memory.add_watch("Explain X", "Explain X", "engineer")
    llm = FakeLLM()

    async def noop_emit(e):
        pass

    await check_due_watches(memory, llm, FakeTavily(), emit=noop_emit,
                           probe_fn=lambda *a, **k: _async_true(),
                           daily_token_budget=1000)
    assert memory.list_watches()[0]["last_status"] == "budget-limited"
    assert llm.prompts == []


async def _async_true():
    return True
