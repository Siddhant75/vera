# Shine Pass Implementation Plan (verdict transparency + minors M1–M9)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Vera's moat visible (prosecutor evidence + per-model votes in the report), surface personalization (notes-considered) and watcher output (in-app digests), and fix all 9 code-level deferred minors.

**Architecture:** No new subsystems. Verdict objects gain optional `votes`/`prosecution` fields that flow through the existing pipeline into `claim_proofs` (report JSON — no DB migration). Watches table gains one column (`last_digest`) with an `ALTER TABLE` guard. All enforcement stays deterministic.

**Tech Stack:** FastAPI/SQLite/pydantic backend, Vite React frontend, pytest.

**Spec:** This plan IS the spec — scope agreed 2026-10-29 in session: re-verdict deferred minors under "winning project" lens; 3 shine gaps named (moat invisible, personalization invisible, digest invisible).

## Global Constraints

- All LLM inference via Nebius Token Factory; Tavily only search API. Tests use fakes from `tests/conftest.py` — never real API calls.
- No `response_format` json_schema — EVER (DECISIONS.md).
- Never commit `.env` or `vera.db`.
- Privacy: note CONTENT never rendered into reports or digests — counts and digests of REPORT changes only.
- Windows dev machine: pytest runs from `backend/` with venv activated; frontend verify = `npm run build`.

## Review Focus

1. **Old `vera.db` without `last_digest` column** — Memory must migrate on open, not crash. Test in Task 4 Step 1 (second test opens a legacy-schema DB).
2. **Legacy verdicts without `votes`/`prosecution`** (old report JSON re-rendered, or vote collection short-circuited) — claim_proofs entries may lack the new keys; UI must render without crashing. Pinned by synthesizer test asserting keys exist via `.get`, and frontend defensive render (Task 2).
3. **Probe where ALL fresh results are trust-excluded domains** — must count as NOT changed (a banned domain appearing is not news). Test in Task 5 Step 1.
4. **Webhook returning 500** — with `raise_for_status()` added, the failure must be caught by the existing try/except and the watch must still complete as `changed`. Test in Task 5 Step 1.
5. **Skill run 429 in frontend** — `runSkillV2` must throw on non-2xx so `App.runByName`'s catch resets `running`; no stuck "Researching…". No JS test runner in repo (out of scope) — pinned by `npm run build` + code check in Task 8; backend 429 JSONResponse shape already tested.

---

### Task 1: Verdict transparency — votes + prosecution into Verdict and claim_proofs

**Files:**
- Modify: `backend/app/models.py:33-38` (Verdict)
- Modify: `backend/app/pipeline/verifier.py:88-132` (_prosecute / verdict construction)
- Modify: `backend/app/pipeline/synthesizer.py:92-94` (claim_proofs)
- Test: `backend/tests/test_verifier.py`, `backend/tests/test_synthesizer.py`

**Interfaces:**
- Consumes: existing `_prosecute(claim, evidence) -> str` (refutation text, "" if none); `verify_claims(...) -> list[Verdict]`; per-model round verdicts already available as `round_verdicts` inside `verify_claims`.
- Produces: `Verdict` gains `votes: list[dict] = []` (items `{"model": str, "verdict": str, "reason": str}` — the FINAL deciding round) and `prosecution: str = ""` (counter-evidence text, truncated to 800 chars). `claim_proofs[claim_id]` gains keys `votes` and `prosecution`. `save_verdicts` unchanged (ignores extra dict keys).

- [ ] **Step 1: Write the failing tests**

In `test_verifier.py` (fake LLM whose verifier-model responses include one disagreement so a full round runs):
```python
def test_verdict_carries_votes_and_prosecution(...):  # build with existing FakeLLM/FakeTavily fixtures
    ...
    assert all("votes" in v.model_dump() for v in verdicts)
    v0 = verdicts[0]
    assert v0.votes and set(v0.votes[0]) == {"model", "verdict", "reason"}
    assert isinstance(v0.prosecution, str)
```
In `test_synthesizer.py`:
```python
def test_claim_proofs_include_votes_and_prosecution():
    # verdicts input: one Verdict with votes=[{"model": "m1", "verdict": "supported", "reason": "r"}],
    # prosecution="counter text"
    ...
    proof = report.claim_proofs[cid]
    assert proof["votes"] == [{"model": "m1", "verdict": "supported", "reason": "r"}]
    assert proof["prosecution"] == "counter text"
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_verifier.py tests/test_synthesizer.py -v` → FAIL (unexpected fields / KeyError).

- [ ] **Step 3: Implement** — `models.py`: add the two fields to `Verdict` (defaults empty — legacy safe). `verifier.py`: in the verdict construction path, set `votes=[{"model": m, "verdict": r.get("verdict", ""), "reason": r.get("reason", "")} for m, r in zip(models, final_round)]` and `prosecution=prosecution[:800]`. `synthesizer.py:92`: add `"votes": v.votes, "prosecution": v.prosecution` to the proof dict.

- [ ] **Step 4: Run to pass** — same command, plus full suite `python -m pytest tests/ -q` (129+ green; orchestrator/save_verdicts unaffected because `model_dump()` extras are ignored downstream).

- [ ] **Step 5: Commit** — `git commit -m "feat: verdicts carry per-model votes + prosecutor counter-evidence into report proofs"`

### Task 2: Frontend — show the adversarial fight in claim proof expansion

**Files:**
- Modify: `frontend/src/components/ReportView.jsx` (ClaimRow expanded proof)
- Verify: `frontend/package.json` build only

**Interfaces:**
- Consumes: `claim_proofs[claim_id]` = `{verdict, reason, web_checked, votes: [{model, verdict, reason}], prosecution: str}` — all new keys possibly absent (legacy).
- Produces: expansion renders "Model votes" lines (`model → verdict — reason`) and a "Prosecutor searched for counter-evidence" block when `prosecution` non-empty. Defensive: `.get`-style access (`proof.votes || []`).

- [ ] **Step 1: Implement** — extend the existing expandable proof section. Short model names: strip org prefix (`id.split("/").pop()`).
- [ ] **Step 2: Verify** — `npm run build` passes; manual: run a research, expand a claim, votes + prosecution block render.
- [ ] **Step 3: Commit** — `git commit -m "feat: claim proof expansion shows model votes + prosecutor evidence"`

### Task 3: Notes-considered visibility

**Files:**
- Modify: `backend/app/pipeline/synthesizer.py:20-24` (signature + report field)
- Modify: `backend/app/pipeline/orchestrator.py` (pass count)
- Modify: `backend/app/models.py:47-57` (ResearchReport)
- Modify: `frontend/src/components/ReportView.jsx` (one line)
- Test: `backend/tests/test_synthesizer.py`, `backend/tests/test_orchestrator.py`

**Interfaces:**
- Produces: `synthesize(..., notes_count: int = 0)`; `ResearchReport.notes_considered: int = 0`. Orchestrator passes `notes_count=len(notes)` (notes already loaded there).
- UI: when `report.notes_considered > 0`, ReportView shows `Considered {n} private note(s) for this topic` — count only, never content.

- [ ] **Step 1: Failing tests** — synthesizer test asserts `report.notes_considered == 2` when `notes_count=2`; orchestrator test asserts report dict field equals number of notes added for the topic.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** the three backend edits.
- [ ] **Step 4: Run → PASS** (full suite).
- [ ] **Step 5: Frontend line** in ReportView + `npm run build`.
- [ ] **Step 6: Commit** — `git commit -m "feat: report shows how many private notes shaped the research"`

### Task 4: In-app digest storage + display

**Files:**
- Modify: `backend/app/memory.py` (schema block after watches CREATE, `set_watch_result`, `list_watches`)
- Modify: `backend/app/watcher.py:71-79` (store digest text)
- Modify: `frontend/src/components/WatchToggle.jsx` (render digest)
- Test: `backend/tests/test_memory.py`, `backend/tests/test_watcher.py`

**Interfaces:**
- Produces: `watches.last_digest TEXT` column (nullable); `set_watch_result(..., digest: str | None = None)` stores it (COALESCE like other optionals); `list_watches()` returns `last_digest`; watcher passes `digest=text` on the `changed` path. UI: expandable per-watch row showing `last_digest` when present.

- [ ] **Step 1: Failing tests**
```python
def test_watch_digest_roundtrip(tmp_path):
    m = Memory(str(tmp_path / "t.db"))
    wid = m.add_watch("k8s", "brief", "engineer")
    m.set_watch_result(wid, "changed", run_uuid="r1", changes=2, digest="Vera update: 2 changes — X; Y")
    assert m.list_watches()[0]["last_digest"] == "Vera update: 2 changes — X; Y"

def test_memory_migrates_legacy_watches_table(tmp_path):
    # create DB with pre-shine watches schema (no last_digest), then open with Memory
    import sqlite3
    p = str(tmp_path / "legacy.db")
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE watches (id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT, brief TEXT, "
              "persona TEXT, interval_hours INTEGER, last_checked TEXT, last_run_uuid TEXT, "
              "last_status TEXT, last_changes INTEGER)")
    c.execute("INSERT INTO watches (topic, brief, persona, interval_hours) VALUES ('t','b','e',6)")
    c.commit(); c.close()
    m = Memory(p)
    m.set_watch_result(1, "changed", digest="d")
    assert m.list_watches()[0]["last_digest"] == "d"
```
Watcher test: `check_due_watches` with changed probe + webhook_url unset still stores digest in watch row.
- [ ] **Step 2: Run → FAIL** (no column / KeyError).
- [ ] **Step 3: Implement** — migration after the schema block:
```python
cols = [r[1] for r in self._conn.execute("PRAGMA table_info(watches)").fetchall()]
if "last_digest" not in cols:
    self._conn.execute("ALTER TABLE watches ADD COLUMN last_digest TEXT")
```
`set_watch_result` gains `digest` param with `COALESCE(?, last_digest)`; `list_watches` selects + returns it; watcher passes `digest=text` (text built once, reused for webhook).
- [ ] **Step 4: Run → PASS** (full suite).
- [ ] **Step 5: WatchToggle UI** — expandable digest text per watch row; `npm run build`.
- [ ] **Step 6: Commit** — `git commit -m "feat: watch digests stored and visible in-app"`

### Task 5: Watcher fixes — webhook raise_for_status (M1) + probe trust filter (M2)

**Files:**
- Modify: `backend/app/watcher.py:23-39` (probe_changed, _post_digest)
- Test: `backend/tests/test_watcher.py`, `backend/tests/test_webhook.py`

**Interfaces:**
- Produces: `probe_changed` drops results whose domain is in `memory.get_profile()["excluded_sources"]` BEFORE the known-URL comparison (use existing `domain_of` from `memory.py`). `_post_digest` calls `resp.raise_for_status()` — the existing try/except in `check_due_watches` logs it; watch still completes `changed`.

- [ ] **Step 1: Failing tests**
```python
def test_probe_ignores_excluded_domains(...):  # profile excludes example.com; FakeTavily returns only example.com URLs
    ... assert changed is False
def test_probe_change_only_on_excluded_domain_not_changed(...):  # mix of known + excluded-new → False
def test_post_digest_raises_on_http_error():  # httpx.MockTransport returning 500 → pytest.raises(httpx.HTTPStatusError)
def test_watch_completes_changed_when_webhook_500(...):  # monkeypatch _post_digest to raise; watch row last_status == "changed"
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** both edits (probe filter = 3 lines; raise_for_status = 1 line; capture `resp` first).
- [ ] **Step 4: Run → PASS** (full suite).
- [ ] **Step 5: Commit** — `git commit -m "fix: probe respects excluded domains; webhook failures raise and log"`

### Task 6: Shutdown await (M3) + digest_webhook_url DI (M4)

**Files:**
- Modify: `backend/app/main.py:60-70,46-53,262-263` (lifespan, create_app signature, build_app)
- Test: `backend/tests/test_api.py` (or test file where lifespan/watch tests live)

**Interfaces:**
- Produces: `create_app(..., digest_webhook_url: str = "")` — `state["webhook_url"] = digest_webhook_url` (no `Settings()` read inside). `build_app` passes `settings.digest_webhook_url`. Lifespan stores `app.state.watch_task = task`; on shutdown: `task.cancel()` then `await` it suppressing `CancelledError`.

- [ ] **Step 1: Failing tests**
```python
def test_shutdown_awaits_watch_task(...):  # create_app with watch_interval_minutes=1, sentinel watch_loop recording
    # cancellation; TestClient context exit; assert sentinel saw CancelledError and no pending task
def test_digest_webhook_url_injected(...):  # create_app(..., digest_webhook_url="http://x") → state["webhook_url"] == "http://x"
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.** Existing tests that monkeypatch `DIGEST_WEBHOOK_URL` env switch to passing the param.
- [ ] **Step 4: Run → PASS** (full suite).
- [ ] **Step 5: Commit** — `git commit -m "refactor: graceful watch shutdown; digest webhook injected via DI"`

### Task 7: Test hygiene (M5–M7) + missing API tests (M8)

**Files:**
- Modify: `backend/tests/test_webhook.py` (delete dead `_patched_probe`), `backend/tests/test_memory_control.py` (fix tautological assert), `backend/tests/test_notes.py` (delete dead double FakeLLM line), `backend/tests/test_api.py` (2 new tests)

- [ ] **Step 1: Write the failing tests (M8)**
```python
def test_post_note_returns_warnings_and_saves(...):  # content with "sk-abc123..."-style pattern → warnings non-empty AND note persisted via GET /api/notes
def test_purge_endpoint_wipes_everything(...):  # seed run + note + profile via API, DELETE /api/memory, then:
    # GET /api/memory → runs == []; GET /api/profile → empty/defaults; GET /api/notes?topic=... → []
```
- [ ] **Step 2: Run → FAIL** (purge test may pass if endpoint already correct — that is the point: it must EXIST and be meaningful; fix the tautological assert in the existing purge test in the same step so it truly asserts profile wiped).
- [ ] **Step 3: Delete dead code** — `_patched_probe` helper, duplicate FakeLLM line.
- [ ] **Step 4: Run full suite → PASS.**
- [ ] **Step 5: Commit** — `git commit -m "test: API-level purge + notes-warnings tests; remove dead test code"`

### Task 8: Frontend error surface (M9)

**Files:**
- Modify: `frontend/src/api.js:79-84` (runSkillV2), `frontend/src/App.jsx:24-44` (runByName)
- Verify: `npm run build`

**Interfaces:**
- Produces: `runSkillV2` — `const res = await fetch(...); const data = await res.json(); if (!res.ok) throw new Error(data.error || "skill run failed"); return data;`. `runByName` catch: set `runError` state (new) → rendered as a small red line above the pipeline view; cleared on next run start.

- [ ] **Step 1: Implement** both edits (App catch already resets `running` — keep; add message).
- [ ] **Step 2: Verify** — `npm run build` passes; manual check: with budget exhausted, skill run shows the 429 message, UI not stuck.
- [ ] **Step 3: Commit** — `git commit -m "fix: skill-run errors surface in UI instead of hanging"

### Task 9: Docs — DECISIONS.md, README, CLAUDE.md (M10 folded in)

**Files:**
- Modify: `docs/DECISIONS.md` (new section: shine-pass rulings + minors resolution), `README.md` (verification-transparency bullet in "How It Works"; notes-considered line in Security/Privacy scope), `CLAUDE.md` (status + module list refresh)

- [ ] **Step 1: DECISIONS.md** — add: votes/prosecution stored in report JSON (no migration, legacy keys absent-safe); notes_considered count-only (privacy: content never rendered); last_digest column + ALTER migration; probe exclusion filter ruling; M10 ruling (brief-slug text goes to Tavily via probe/fallback = accepted behavior, notes protected).
- [ ] **Step 2: README** — under "How It Works" verify bullet: proof expansion shows each model's vote and the prosecutor's counter-evidence. Under Security: "report shows HOW MANY notes informed it — never what they said."
- [ ] **Step 3: CLAUDE.md** — status line (tests count, shine pass date), architecture module list gains `watcher.py, brief.py, budget.py, privacy.py, skills.py`.
- [ ] **Step 4: Commit** — `git commit -m "docs: shine pass — verdict transparency, notes visibility, digest storage"`

## Verification (whole pass)

1. `cd backend && python -m pytest tests/ -q` — full suite green (≥136 expected).
2. `cd frontend && npm run build` — passes.
3. Live smoke (keys in `.env`): fresh run → expand a claim → votes + prosecution visible; report shows notes line when notes exist; watch a topic → digest row visible in WatchToggle.
