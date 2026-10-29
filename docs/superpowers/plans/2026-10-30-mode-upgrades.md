# Mode Upgrades Implementation Plan (run provenance, watch re-freeze, error backoff)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the two research modes inspectable and cheap: every run records which mode created it (manual/delta/skill/watch), watches are editable without delete+recreate, and repeatedly-failing watches back off instead of burning a probe search every cycle.

**Architecture:** One new runs column (`source`), one new watches column (`error_count`), both PRAGMA-guarded ALTERs (same pattern as `last_digest`). `run_research` gains a `source` param threaded from the three entry points. Watch edit = `PUT /api/watch/{id}` partial update. Backoff = due-math multiplier `2^min(error_count, 4)`, reset on any non-error outcome.

**Tech Stack:** Existing patterns; no new deps.

**Spec:** Session verdict 2026-10-30, improvements 1-3 (user approved). Improvement 4 (watch run history) deferred; 5 (stale skill vars) rejected for submission.

## Global Constraints

- Tests use fakes; never real API calls. Deterministic gates stay code-owned.
- Never commit `.env` or `vera.db`.

## Review Focus

1. **Legacy DBs** — `runs.source` and `watches.error_count` must ALTER in place on old `vera.db` (PRAGMA-guarded), and old rows must read back with defaults (`source="manual"`, `error_count=0`). Test opens a legacy-schema DB.
2. **Backoff determinism** — after 2 consecutive probe errors, a watch with interval 1h is due only at `≥ 4h`; backoff caps at 16× interval; ANY non-error outcome resets the count. Tests pin the math, not wall-clock.
3. **Provenance defaults** — runs saved without an explicit source (existing tests, old call paths) read back `"manual"`. Full suite is the gate.
4. **Watch edit mid-flight** — updating a watch between probe and delta run uses the OLD brief for the in-flight run and the NEW brief next cycle (no partial-brief runs). By-inspection + existing watcher test structure.

---

### Task 1: Run provenance — `source` on every run

**Files:**
- Modify: `backend/app/memory.py` (schema ALTER, `save_run`, `list_runs`), `backend/app/pipeline/orchestrator.py` (`run_research(..., source: str = "manual")` → `save_run(..., source=source)`), `backend/app/main.py` (`ResearchIn.source: str = ""`, post_research computes `"skill" if r.source=="skill" else "delta" if r.delta else r.source or "manual"`), `backend/app/watcher.py` (`run_research(..., source="watch")`)
- Modify: `frontend/src/components/MemoryPanel.jsx` (render source tag per run)
- Test: `backend/tests/test_memory.py`, `backend/tests/test_orchestrator.py`, `backend/tests/test_skills_v2.py`

**Interfaces:**
- `save_run(brief, persona, topic_key, report, run_uuid=None, source: str = "manual")` — runs rows carry it; `list_runs()` returns `source`.
- `run_research(..., source: str = "manual")`. Entry points: post_research → `r.source or ("delta" if r.delta else "manual")`; run_skill → `source="skill"`; watcher → `source="watch"`. Allowed values {"manual","delta","skill","watch"} — anything else stored as-is (honesty over validation).

- [ ] **Step 1: Failing tests** — memory: `save_run(..., source="watch")` → `list_runs()[0]["source"] == "watch"`; legacy-schema test (CREATE runs without source column → open → save → reads "manual"). orchestrator: `run_research(..., source="skill")` persists. skills_v2: skill-run report's run row has `source == "skill"`.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** (ALTER after PRAGMA check, same pattern as last_digest).
- [ ] **Step 4: Full suite → PASS.**
- [ ] **Step 5: MemoryPanel** — small `[source]` tag next to each run; `npm run build`.
- [ ] **Step 6: Commit** — `feat: every run records its mode — manual/delta/skill/watch`

### Task 2: Watch re-freeze — PUT /api/watch/{id}

**Files:**
- Modify: `backend/app/memory.py` (`update_watch`), `backend/app/main.py` (`WatchUpdate` model + route)
- Modify: `frontend/src/components/WatchToggle.jsx` (✎ button → inline prompt for brief/interval)
- Test: `backend/tests/test_memory.py`, `backend/tests/test_api.py`

**Interfaces:**
- `memory.update_watch(watch_id: int, topic: str | None = None, brief: str | None = None, persona: str | None = None, interval_hours: int | None = None) -> None` — None = keep (COALESCE); interval re-clamped ≥1 when provided. 404 on unknown id.
- `PUT /api/watch/{id}` body = WatchUpdate (all optional). Returns `{"ok": True}`.

- [ ] **Step 1: Failing tests** — memory: update brief + interval → `list_watches()[0]` reflects both, other fields intact; interval 0 → clamped to 1. API: PUT unknown id → 404; PUT with `{}` → unchanged.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** backend + WatchToggle ✎ (prompt-based, consistent with panel's minimal style).
- [ ] **Step 4: Full suite → PASS; npm run build.**
- [ ] **Step 5: Commit** — `feat: watches editable in place (PUT /api/watch/{id})`

### Task 3: Error backoff for watches

**Files:**
- Modify: `backend/app/memory.py` (watches `error_count` ALTER, `set_watch_result` error path bumps, success path resets), `backend/app/watcher.py` (due-math multiplier)
- Test: `backend/tests/test_watcher.py`

**Interfaces:**
- `watches.error_count INTEGER` (legacy → 0 via ALTER default). `list_watches()` returns `error_count`.
- `check_due_watches` due-math: `due if now − last_checked ≥ interval_hours × (2 ** min(error_count, 4))`. Probe error → `error_count += 1` (via set_watch_result param `error: bool` — implementation detail); changed/no-change/budget-limited → reset 0.
- Deterministic tests use the existing `now` param — no sleeps.

- [ ] **Step 1: Failing tests**
```python
async def test_watch_backoff_after_errors(memory):        # interval 1h; two cycles with probe_fn raising; now advanced 1h then 3h → second check NOT due (probe calls == 1); now advanced +1h more (4h total) → due again
async def test_backoff_resets_on_success(memory):         # after a changed run, next cycle due at plain interval
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Full suite → PASS.**
- [ ] **Step 5: Commit** — `feat: failing watches back off exponentially (deterministic, capped 16x)`

### Task 4: Docs

**Files:** `docs/DECISIONS.md` (provenance + re-freeze + backoff rulings), `README.md` (Track line: run provenance visible in memory panel), `CLAUDE.md` (status line + watcher bullet gains backoff/provenance)

- [ ] **Step 1: Update docs. Commit** — `docs: run provenance, watch edit, error backoff`

## Verification

1. `cd backend && python -m pytest tests/ -q` — full suite green (target ≥173).
2. `cd frontend && npm run build` — passes.
3. Live smoke: run research + skill + watch → memory panel shows distinct source tags; edit a watch brief; error a watch twice → observe skipped cycle.
