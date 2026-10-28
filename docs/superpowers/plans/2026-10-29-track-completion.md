# Track Completion: Topic Watch + Skills + Deployment + Tavily Labels

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Personal-AI-track gaps — always-on Topic Watch, reusable Skills, deployment path — and make Tavily's four roles judge-visible.

**Architecture:** Watcher = in-app asyncio loop (FastAPI lifespan): due watches get a deterministic freshness probe (1 Tavily search vs stored sources of the last run — no LLM), changed topics trigger an automatic delta run through the existing `run_research`. Skills = named recipes (persona + brief template + topic + source prefs) stored in SQLite, one-click invoked. Deployment: Dockerfile + Render blueprint, Vercel frontend, Nebius Serverless documented optional. Tavily calls get role labels (`grounding|prosecution|recheck`) surfaced in telemetry.

**Tech Stack:** existing stack — FastAPI, SQLite, httpx, pytest-asyncio, Vite React. No new dependencies.

**Spec:** `docs/DECISIONS.md` §"Planned next (approved 2026-10-28)" + track-paragraph analysis (same file, 2026-10-28 sections). This plan implements those rulings.

## Global Constraints

- All LLM inference via Nebius Token Factory; Tavily for all search (never both changed)
- `DAILY_TOKEN_BUDGET` gates watcher runs too — watch-triggered research goes through the same `run_research` path and budget guard as manual runs
- No new Python/npm dependencies
- Watcher must never crash the scheduler loop: one watch failing ≠ others skipped ≠ loop dead
- Trust filter (`memory.trust_multiplier`) applies to probe searches; excluded domains never appear anywhere
- Frontend: no new components frameworks; plain Vite React patterns as existing (`src/components/`)

## Review Focus

1. **Watcher loop dies on one bad watch** — expect: exception logged, remaining watches still probed, loop alive next tick. Pinned in Task 25 (fake probe raising on second watch).
2. **Probe Tavily failure** — expect: watch status `error`, no delta run, retried next cycle. Pinned in Task 25.
3. **Interval ≤ 0 or garbage** — expect: clamped to ≥1 hour, never a busy-loop. Pinned in Task 25.
4. **Probe search itself exhausted the run budget** — probe uses Tavily, not Token Factory: `DAILY_TOKEN_BUDGET` (tokens) does NOT gate probes; probes bounded by watch count × 1 search. Expect: probe never triggers `run_research` when the daily token budget is exhausted (guard 429s → digest status `budget-limited`). Pinned in Task 25.
5. **Skill with empty name / missing brief template invoked** — expect: 422 validation, no run started. Pinned in Task 26.

---

## File Structure

```
backend/
  app/telemetry.py        [modify] tavily counters split by role: tavily_by_role {grounding,prosecution,recheck}
  app/search.py           [modify] TavilyClient.search(query, max_results=5, role="grounding")
  app/pipeline/searcher.py    [modify] passes role="grounding"
  app/pipeline/verifier.py    [modify] passes role="prosecution" (prosecutor) / "recheck" (disagreement re-check)
  app/memory.py           [modify] watches table + CRUD; skills table + CRUD
  app/watcher.py          [create] probe_topic, check_due_watches, watch_loop
  app/main.py             [modify] /api/watch CRUD, /api/skills CRUD, lifespan starts watch_loop
  frontend/src/components/WatchToggle.jsx   [create]
  frontend/src/components/SkillsPanel.jsx   [create]
  frontend/src/components/TelemetryPanel.jsx [modify] role-split Tavily display
  frontend/src/App.jsx    [modify] integrate both
  frontend/src/api.js     [modify] watch + skills clients
deploy/
  Dockerfile              [create]
  render.yaml             [create]
  DEPLOY.md               [create] Render/Railway/fly steps; Vercel frontend; Nebius Serverless optional
tests/test_telemetry_roles.py  [create]
tests/test_watcher.py    [create]
tests/test_skills.py     [create]
```

---

### Task 24: Tavily role labels

**Interfaces (Produces):**
- `TavilyClient.search(query, max_results=5, role="grounding")` — role ∈ {grounding, prosecution, recheck}; unknown role → ValueError
- `telemetry.snapshot()` gains `tavily_grounding`, `tavily_prosecution`, `tavily_recheck` (plus legacy `tavily_queries` total)
- Verifier passes `role="prosecution"` in `_prosecute`, `role="recheck"` in the disagreement re-check; searcher passes `role="grounding"`

- [ ] **Step 1: Failing tests** (`tests/test_telemetry_roles.py`): (a) search with role counts into `tavily_prosecution`; (b) unknown role raises ValueError; (c) default role = grounding; (d) verifier evidence prompts unchanged (existing suite stays green = wiring correct).

- [ ] **Step 2:** run → FAIL. **Step 3:** implement (search.py role param + validation; telemetry.add gains `tavily_role` handling; verifier/searcher call sites; TelemetryPanel.jsx shows `Tavily: 8 grounding · 6 prosecution · 2 re-check`). **Step 4:** run full suite → PASS (93 + ~4) + frontend build. **Step 5:** commit `feat: role-labeled Tavily telemetry (grounding/prosecution/recheck)`

### Task 25: Topic Watch (always-on)

**Interfaces:**
- Memory: `add_watch(topic, brief, persona, interval_hours=6) -> int`, `remove_watch(id)`, `list_watches() -> list[dict]` (each with `last_digest`), `set_watch_result(id, status, run_uuid=None, changes=None)`; watches table `{id, topic, brief, persona, interval_hours, last_checked, last_run_uuid, last_status, last_changes}`
- Watcher (`app/watcher.py`):
  - `async def probe_changed(memory, tavily, watch: dict) -> bool` — 1 Tavily search; compares top-5 URLs vs `memory.get_sources(watch["last_run_uuid"])` (None → no history → True: first watch runs immediately).
  - `async def check_due_watches(memory, llm, tavily, now=None)` — for each watch where `last_checked + interval` passed: probe; changed → `run_research(brief, persona, topic, delta=True, emit=noop)`; set result status ∈ {changed, no-change, error, budget-limited}; `last_checked = now` on EVERY attempt (success or not).
  - `async def watch_loop(app_state, interval_minutes=30)` — `while True: await check_due_watches(...); await asyncio.sleep(interval_minutes*60)`; started in FastAPI lifespan, cancelled on shutdown. Env: `WATCH_INTERVAL_MINUTES` (default 30).
- API: `POST /api/watch {topic, brief, persona, interval_hours}` (interval clamped ≥1), `GET /api/watch`, `DELETE /api/watch/{id}`
- Frontend: `WatchToggle` on a completed report's topic; watches list panel showing status + changes count

**Review Focus pins:** (1) probe raising on watch #2 → watch #3 still probed, loop alive (test: fake probe side-effect list, assert 3 watches processed, status of #2 = error); (2) probe Tavily SearchError → status `error`, `run_research` NOT called (assert FakeLLM.prompts empty); (3) `interval_hours=0` → clamped 1 (test add_watch + due math); (4) token budget exhausted (telemetry.tf_tokens ≥ budget via `daily_token_budget` on create_app) → status `budget-limited`, no LLM call; changed-probe = new URL detection (test with get_sources preloaded vs probe results).

- [ ] Steps: failing tests (test_watcher.py ~6 cases) → FAIL → implement watcher + memory + API → PASS full suite → frontend (WatchToggle + list, build passes) → commit `feat: topic watch — always-on scheduler, freshness probe, delta digest`

### Task 26: Skills (reusable research recipes)

**Interfaces:**
- Memory: `upsert_skill(name, persona, brief_template, topic, trusted=[], excluded=[]) -> int`, `list_skills() -> list[dict]`, `delete_skill(name)`; skills table `{name UNIQUE, persona, brief_template, topic, trusted_sources, excluded_sources}` (upsert on name conflict)
- API: `POST /api/skills` (name + brief_template required — 422 otherwise: Review Focus pin), `GET /api/skills`, `DELETE /api/skills/{name}`, `POST /api/skills/{name}/run` → applies skill (sets profile sources via `memory.set_profile`, returns run via `POST /api/research` semantics with skill's brief/topic/persona → `{run_id}`)
- Frontend: `SkillsPanel` — save current form as skill, list, one-click "Run skill"

- [ ] Steps: failing tests (test_skills.py: upsert-overwrite, list, delete, run applies sources + starts run, 422 on empty name/brief) → FAIL → implement → PASS → frontend build → commit `feat: reusable research skills — named recipes, one-click run`

### Task 27: Deployment + docs refresh

**Files:** `deploy/Dockerfile` (python base, install backend reqs, build frontend into image, uvicorn serves app + mounted static, env-only secrets), `deploy/render.yaml` (web service, env vars: TOKEN_FACTORY_API_KEY, TAVILY_API_KEY, PLANNER_MODEL, VERIFIER_MODELS, DAILY_TOKEN_BUDGET, WATCH_INTERVAL_MINUTES; disk mount for vera.db), `deploy/DEPLOY.md` (Render/Railway/fly steps; Vercel frontend alternative; Nebius Serverless Endpoint/Job optional appendix with cookbook link).

- [ ] Steps: Dockerfile builds (`.dockerignore`: .venv, node_modules, .env, vera.db*, .superpowers); DEPLOY.md written; DECISIONS.md gains the three rulings (watch probes are Tavily-side, not token-gated; skills upsert on name; hosting = Render/Vercel primary, Serverless optional); README deploy section replaced with pointer to deploy/DEPLOY.md; commit `feat: deployment path + docs refresh`

---

## Verification

1. `cd backend && python -m pytest tests/ -q` — full suite green (target ≥105 tests)
2. Live smoke: add watch for an existing topic → force due (interval clamp) → observe probe + delta digest status in `GET /api/watch`; confirm DAILY_TOKEN_BUDGET respected when exhausted
3. `docker build -f deploy/Dockerfile .` succeeds; `deploy/DEPLOY.md` steps followed manually on Render free tier
4. Frontend build + manual: WatchToggle + SkillsPanel functional; telemetry shows role split
