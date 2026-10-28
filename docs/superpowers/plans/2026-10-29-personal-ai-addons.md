# Personal-AI Add-ons: Notes + Webhook Delivery + Memory Control + Skills v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every clause of the Personal-AI track paragraph literally true — private user evidence with a deterministic privacy gate, research digests delivered into daily workflows, user-controlled memory, and genuinely reusable skills. Task 27 (hosting) is deliberately excluded — held for separate discussion.

**Architecture:** Notes = local-only user evidence injected into planner/drafter prompts, with a deterministic privacy gate (`app/privacy.py`) that blocks note-content leakage into Tavily queries and warns on pasted secrets. Webhook = watcher posts a changes digest to an operator-set URL after each `changed` watch run. Memory control = list/delete/purge endpoints + panel. Skills v2 = `{var}` template filling at run time + optional auto-watch on run.

**Tech Stack:** existing stack — FastAPI, SQLite, httpx, pytest-asyncio, Vite React. No new dependencies (webhook = plain httpx POST; secrets scan = stdlib `re`).

**Spec:** `docs/DECISIONS.md` (2026-10-28 rulings + track analysis). This plan implements the four add-ons greenlit in discussion; hosting (old Task 27) explicitly out of scope here.

## Global Constraints

- All LLM inference via Nebius Token Factory; all search via Tavily (unchanged)
- Note content NEVER appears in any Tavily query — enforced by code gate, not prompt plea
- Note storage: local SQLite only, never synced, never rendered into unused-sources or exports
- Webhook URL comes from env (`DIGEST_WEBHOOK_URL`) — never accepted from API input (SSRF-safe)
- Secrets warning = warn-and-save (user autonomy), never silently blocked
- No new Python/npm dependencies

## Review Focus

1. **Note content leaks into a Tavily query** (planner saw the note, generated a query quoting it) — expect: query word-4-gram-overlapping note content is blocked/stripped before dispatch. Pinned in Task 28.
2. **User pastes a secret (API key, password) into notes** — expect: loud warning returned at save AND stored anyway (autonomy); secret never re-emerges in queries (gate from #1 covers). Pinned in Task 28.
3. **Notes attached to topic X surface in a run for topic Y** — expect: never; notes are topic-keyed. Pinned in Task 28.
4. **Webhook endpoint down / slow** — expect: logged, watch still completes as `changed`, next cycle retries delivery naturally (new digest). Pinned in Task 29.
5. **Purge-all while watcher is running** — expect: empty watch list handled gracefully, loop alive. Pinned in Task 30.

---

## File Structure

```
backend/
  app/privacy.py            [create] scan_for_secrets, gate_queries (n-gram overlap vs notes)
  app/memory.py             [modify] notes table CRUD; list_runs/delete_run/purge_all
  app/watcher.py            [modify] digest webhook POST after changed runs
  app/pipeline/orchestrator.py [modify] load notes, pass to planner+drafter, gate queries at dispatch
  app/pipeline/searcher.py  [modify] accept gated query callable
  app/main.py               [modify] /api/notes, /api/memory, /api/skills v2 (vars, watch)
  frontend/src/components/NotesPanel.jsx     [create]
  frontend/src/components/MemoryPanel.jsx    [create]
  frontend/src/components/SkillsPanel.jsx    [modify] vars + run-and-watch
  frontend/src/api.js       [modify] notes/memory/skills clients
  README.md                 [modify] security section (never-paste list)
  docs/DECISIONS.md         [modify] rulings after each task
tests/test_privacy.py       [create]
tests/test_notes.py         [create]
tests/test_webhook.py       [create]
tests/test_memory_control.py [create]
tests/test_skills_v2.py     [create]
```

---

### Task 28: Private context notes + privacy gate

**Files:** Create `app/privacy.py`, `tests/test_privacy.py`, `tests/test_notes.py`, `frontend/src/components/NotesPanel.jsx`; modify memory/orchestrator/searcher/main/api.js/README.

**Interfaces (Produces):**
- `privacy.scan_for_secrets(text) -> list[str]` — pattern names found: `api-key` (`sk-\w{8,}`, `ghp_\w{20,}`, `AKIA[0-9A-Z]{16}`), `password` (`(?i)password\s*[=:]`), `private-key` (`-----BEGIN`), `card-number` (`\b\d{12,19}\b`)
- `privacy.safe_query(query: str, notes: list[str], fallback: str) -> str` — returns query unchanged when notes empty or no word-4-gram overlap with any note; returns `fallback` when the query shares a 4-gram with note content (leak blocked). Single-query form: every Tavily dispatch site calls it (sub-question, prosecutor, re-check)
- Memory: `add_note(topic_key, content) -> (id, warnings)` (content truncated 10_000 chars), `list_notes(topic_key) -> list[dict]`, `delete_note(id)`, notes table `{id, topic_key, content, created_at}`; notes capped at 5 per topic (oldest evicted)
- Orchestrator: `notes = memory.list_notes(tk)` → planner + drafter prompts gain block `USER PRIVATE NOTES (private: never repeat their content in search queries; do not cite as web sources): …` (≤5 notes × 2000 chars); builds `gate = lambda q: safe_query(q, notes, fallback=tk)` and passes it down — searcher gains param `gate=Callable[[str], str]` (default identity), applied to each sub-question query; verifier applies it to prosecutor + re-check queries
- API: `POST /api/notes {topic, content}` → `{id, warnings}`; `GET /api/notes?topic=`; `DELETE /api/notes/{id}`
- Frontend: `NotesPanel` — add note (textarea + warning display listing `scan_for_secrets` hits + never-paste list), list, delete

- [ ] **Step 1: failing tests** — privacy: (a) secrets patterns detected (`sk-abc12345`, `AKIA…`, `password: x`, `-----BEGIN`, 16-digit run); (b) clean text → `[]`; (c) safe_query: query sharing a note 4-gram → fallback returned, unrelated query passes unchanged, empty notes = passthrough. notes: (d) add/list/delete round-trip + truncation at 10k + 5-note eviction; (e) orchestrator: run with note for topic → planner prompt contains note text, FakeTavily queries contain NO note 4-gram; (f) note on topic X absent from run on topic Y; (g) POST /api/notes returns warnings for secret content but stores it. **Step 2:** FAIL. **Step 3:** implement. **Step 4:** full suite PASS. **Step 5:** commit `feat: private context notes with deterministic privacy gate`

### Task 29: Webhook digest delivery

**Files:** modify `app/watcher.py`, `app/config.py`, `tests/test_webhook.py`.

**Interfaces:** Settings gains `digest_webhook_url: str = ""`; `check_due_watches` gains param `webhook_url: str = ""` (wired from settings in `watch_loop`/`main.py` state); after a `changed` result: POST JSON `{text, topic, changes, verdict_summary, run_uuid}` where `text` = `"Vera update on '{topic}': {n} changes — {changes joined '; '}"` to `webhook_url` (httpx POST, 10s timeout); any failure → `log.warning`, watch status unchanged (Review Focus #4).

- [ ] **Step 1: failing tests** — (a) changed run + webhook set → POST captured with topic+changes; (b) webhook returns 500 → status still `changed`, no exception; (c) `no-change` → no POST; (d) webhook_url empty → no POST. **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** commit `feat: watch digests delivered to operator webhook`

### Task 30: Memory control (view + delete + purge)

**Files:** modify `app/memory.py`, `app/main.py`, `tests/test_memory_control.py`; create `frontend/src/components/MemoryPanel.jsx`.

**Interfaces:** Memory: `list_runs(limit=50) -> [{run_uuid, brief, persona, topic_key, created_at}]`, `delete_run(run_uuid)` (cascades verdicts/sources/feedback rows for that uuid), `purge_all()` (wipes runs, verdicts, sources, feedback, watches, notes, skills — everything). API: `GET /api/memory` → `{runs, counts}`, `DELETE /api/runs/{run_uuid}`, `DELETE /api/memory` (purge-all). Frontend: `MemoryPanel` — runs list with delete, purge-all behind a type-to-confirm.

- [ ] **Step 1: failing tests** — (a) list_runs returns seeded rows; (b) delete_run removes run + its verdicts/sources, leaves other runs; (c) purge_all empties every table incl. watches/skills/notes; (d) Review Focus #5: `check_due_watches` with zero watches = no-op (already true — pin it); (e) DELETE /api/memory endpoint empties memory. **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** commit `feat: memory control — view, delete run, purge all`

### Task 31: Skills v2 (template vars + run-and-watch)

**Files:** modify `app/main.py`, `tests/test_skills_v2.py`; modify `frontend/src/components/SkillsPanel.jsx`, `src/api.js`.

**Interfaces:** `POST /api/skills/{name}/run` body `{vars: {…}, watch: false}` — brief template filled with `str.format_map(SafeDict)` where `SafeDict.__missing__` returns `{key}` literal; known conventions: `{topic}`, `{date}` (auto-injected), `{quarter}` (auto from today's date); `watch: true` → `memory.add_watch(filled_topic, filled_brief, persona, 6)` after starting the run; response `{run_id, watch_id?}`. SkillIn gains nothing (skills unchanged at save).

- [ ] **Step 1: failing tests** — (a) `{topic}` + custom `{var}` filled, unknown `{nope}` left literal; (b) `{date}`/`{quarter}` auto-injected; (c) `watch: true` creates watch; (d) run uses filled brief in `run_research` call (FakeLLM prompt contains filled text). **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** commit `feat: skills v2 — template variables, run-and-watch`

---

## Docs (folded into each task, not a separate task)

- Task 28: README gains "Security & privacy" section (never-paste list, what leaves the machine and where); DECISIONS.md gains privacy-gate ruling
- Task 29: DECISIONS.md gains webhook ruling (operator-set URL, SSRF-safe, delivery-failure semantics)
- Task 30: DECISIONS.md gains purge semantics (wipe includes watches/skills/notes; profile too)
- Task 31: DECISIONS.md gains SafeDict ruling (unknown vars literal, never run-blocking)

## Verification

1. `cd backend && python -m pytest tests/ -q` — full suite green (target ≥120 tests)
2. Live smoke: save a note containing the word unique-marker → run research on that topic → note influences planner prompt; watch run → digest POST received by a local `nc`/webhook.site endpoint; purge-all → `GET /api/memory` empty, watcher survives next tick
3. Frontend build + manual: NotesPanel warnings, MemoryPanel purge confirm, SkillsPanel vars form
