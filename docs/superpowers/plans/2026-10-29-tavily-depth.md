# Tavily Depth Pass Implementation Plan (search-side trust, extract verification, sharper probe)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use Tavily's documented capabilities beyond basic search — domain-prefer/exclude in-query, Extract on cited pages, time-ranged freshness probes, community prosecution — to deepen the "Best Use of Tavily" story AND Vera's own verification/personalization/always-on claims.

**Architecture:** No new subsystems. `TavilyClient` gains optional search params + an `extract` method; the four existing dispatch sites (searcher, prosecutor, re-check, probe) opt in per their role. Every new Tavily call stays SearchBudget-gated, privacy-gated (`safe_query`), and failure-tolerant with visible degradation.

**Tech Stack:** httpx (MockTransport tests), pytest, existing FakeTavily/FakeLLM doubles.

**Spec:** Verdict doc from this session's Tavily-capability research (2026-10-29, sources: docs.tavily.com /search /extract /research, changelog). Build ONLY: search-side trust, Extract-on-recheck, time-ranged probe, community prosecution (reddit.com via `include_domains`). Deliberately NOT built: `/research` endpoint and `include_answer` (Tavily's LLM ≠ Nebius Token Factory → hard submission rule + kills the moat), Crawl/Map (site audits ≠ research journey), any X/Threads claim (undocumented, auth-walled).

## Global Constraints

- All LLM inference via Nebius Token Factory; Tavily never reasons — it only finds evidence (no `include_answer`, no `/research`).
- Every Tavily dispatch stays behind: SearchBudget unit (extract batches = 1 unit), `safe_query` gate where query text can echo notes, failure-tolerant catch with visible degradation.
- Domain lists sent to Tavily are USER CONFIG (trusted/excluded sources) — never note content. Privacy rule unchanged.
- Tests use fakes (conftest) or `httpx.MockTransport` — never real API calls. Windows: run pytest from `backend/`.
- Never commit `.env` or `vera.db`.

## Review Focus

1. **`prefer` mode with EMPTY trusted list** — `include_domains_mode` without `include_domains` returns HTTP 400; client must omit both when trusted list is empty. Test in Task 1 (body-asserting handler).
2. **Extract failure / partial failure** — `failed_results` entries and raised `SearchError` must skip the extract silently-with-note, never crash the verifier. Tests in Task 4.
3. **Community prosecution when Reddit returns nothing** — second search adds no evidence lines, claim verdict unaffected. Test in Task 3.
4. **Budget exhaustion between first and second Tavily call** — prosecutor's community search and the re-check's extract each consume separately; exhaustion must produce the SAME visible-degradation behavior as today (skip + reason note), never a crash. Tests in Tasks 3-4.
5. **FakeTavily signature drift** — every existing test double call site must keep working after `search` gains kwargs. Task 2 updates the double; full suite is the gate.

---

### Task 1: TavilyClient — search params, probe role, extract method

**Files:**
- Modify: `backend/app/search.py`
- Test: `backend/tests/test_search.py`

**Interfaces:**
- Produces:
  - `search(query, max_results=5, role="grounding", *, topic=None, time_range=None, include_domains=None, exclude_domains=None) -> list[dict]` — new optional kwargs; keys included in the POST body ONLY when set (never `include_domains_mode` without `include_domains` — Tavily 400s). When `include_domains` set, mode = `"prefer"`. `ROLES += "probe"`.
  - `extract(urls: list[str], query: str | None = None, extract_depth: str = "basic") -> list[dict]` — POST `https://api.tavily.com/extract`, body `{api_key, urls (≤20), query?, extract_depth}`; returns `[{"url": ..., "content": raw_content}]` for `results`, SKIPS `failed_results`. Telemetry: `tavily_extracts` counter. Raises `SearchError` on non-200.
  - Telemetry: `tavily_probe` counter (role like existing `tavily_{role}`).

- [ ] **Step 1: Failing tests** (MockTransport handlers asserting the request BODY, matching test_search.py style):
```python
async def test_search_domain_prefs_in_body():      # include_domains=["a.com"] -> body has include_domains + include_domains_mode="prefer", exclude_domains=[]
async def test_search_no_include_no_mode_key():    # only exclude_domains -> body has exclude_domains, NO include_domains_mode (Tavily 400s otherwise)
async def test_search_topic_and_time_range():      # topic="news", time_range="week" -> both in body
async def test_search_probe_role_telemetry():      # role="probe" -> snapshot()["tavily_probe"] == 1
async def test_extract_maps_results():             # 200 with results:[{url, raw_content}], failed_results:[{url}] -> returns only successes as {url, content}; body has api_key+urls
async def test_extract_500_raises():               # SearchError
```
- [ ] **Step 2: Run → FAIL** (unexpected kwargs / AttributeError extract).
- [ ] **Step 3: Implement** — build body dict with conditional keys; add EXTRACT_URL const; telemetry counters.
- [ ] **Step 4: Run → PASS** + full suite (`python -m pytest tests/ -q`).
- [ ] **Step 5: Commit** — `feat: TavilyClient — domain prefs, probe role, extract method`

### Task 2: FakeTavily kwargs compatibility

**Files:**
- Modify: `backend/tests/conftest.py` (FakeTavily)

**Interfaces:**
- Produces: `FakeTavily.search(self, query, max_results=5, role="grounding", **kw)` — records `self.kwargs.append(kw)`; `self.queries` unchanged (query strings). Existing assertions untouched.

- [ ] **Step 1: Modify double + run full suite** — `python -m pytest tests/ -q` must stay 144+ green (this is the compatibility gate for every later task).
- [ ] **Step 2: Commit** — `test: FakeTavily records search kwargs`

### Task 3: Search-side trust + community prosecution

**Files:**
- Modify: `backend/app/memory.py` (add `clean_domains`)
- Modify: `backend/app/pipeline/searcher.py:8-28`, `backend/app/pipeline/verifier.py:88-108` (_prosecute), `backend/app/pipeline/orchestrator.py` (build prefs, thread through)
- Test: `backend/tests/test_searcher.py`, `backend/tests/test_verifier.py`, `backend/tests/test_orchestrator.py`

**Interfaces:**
- Produces: `Memory.clean_domains(domains: list[str]) -> list[str]` — lowercase, strip scheme/path (urlparse netloc when input looks like a URL), drop empties, dedupe, cap 150.
- `search_sources(plan, tavily, trust_fn, budget=None, gate=None, domain_prefs=None)` where `domain_prefs = {"trusted": [...], "excluded": [...]}` — `_one` passes `include_domains=prefs["trusted"] or None, exclude_domains=prefs["excluded"] or None` (post-hoc trust filter stays — belt and braces).
- `verify_claims(..., domain_prefs=None)` — prosecutor AND re-check searches get `exclude_domains` ONLY (counter-evidence must not be biased toward trusted domains; banned domains still blocked at source).
- Orchestrator: `domain_prefs = {"trusted": memory.clean_domains(profile.get("trusted_sources", [])), "excluded": memory.clean_domains(profile.get("excluded_sources", []))}`.
- Community prosecution: inside `_prosecute`, after the first refutation search, if a query exists AND `budget.try_consume()`: one more search, same query, `include_domains=["reddit.com"], role="prosecution"`; results appended to evidence as `COMMUNITY EVIDENCE ({url}): {title} - {content[:500]}`. Empty result / budget-out / exception → silently absent (verdict path unchanged).

- [ ] **Step 1: Failing tests**
```python
# test_searcher.py
async def test_grounding_search_carries_domain_prefs():   # FakeTavily.kwargs[-1] has include_domains=["trusted.com"], mode handled client-side
async def test_grounding_no_prefs_no_kwargs():            # domain_prefs=None -> kwargs empty
# test_verifier.py
async def test_prosecution_excludes_banned_domains():     # kwargs on prosecution call have exclude_domains, NO include_domains
async def test_community_prosecution_adds_evidence():     # budget allows 2: two prosecution searches (second include_domains=["reddit.com"]), COMMUNITY EVIDENCE reaches voters
async def test_community_prosecution_skipped_when_budget_out():  # SearchBudget(1): first search consumes, no second, verdict unchanged
# test_orchestrator.py
async def test_domain_prefs_threaded_from_profile():      # profile with trusted+excluded -> searcher double sees prefs
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** all four files.
- [ ] **Step 4: Run full suite → PASS.**
- [ ] **Step 5: Commit** — `feat: search-side trust prefs + community prosecution (reddit)`

### Task 4: Extract cited pages on re-check

**Files:**
- Modify: `backend/app/pipeline/verifier.py:110-140` (_verify_one disagreement path)
- Test: `backend/tests/test_verifier.py`

**Interfaces:**
- Produces: on disagreement-triggered re-check, BEFORE the web re-search: if `budget.try_consume()` — `tavily.extract(claim.citation_urls[:20], query=gate(claim.text) if gate else claim.text)`; successful extractions appended to evidence as `FULL PAGE ({url}): {content[:800]}`. `SearchError`/empty → skip, proceed exactly as today (snippet re-check). Re-check search itself unchanged.
- Privacy: extract `query` passes through the same `safe_query` gate as every other dispatch. Extracted page content is public web — allowed in evidence.

- [ ] **Step 1: Failing tests**
```python
async def test_recheck_extracts_cited_pages():            # disagreement + FakeTavily.extract returning [{url, content}] -> "FULL PAGE" in re-vote prompts, extract called once
async def test_recheck_extract_failure_degrades():        # extract raises SearchError -> re-check proceeds snippet-only, no crash
async def test_recheck_extract_skipped_when_budget_out(): # SearchBudget(1) with disagreement -> extract NOT called, web re-search also skipped (existing behavior), reason notes budget-limited
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** — FakeTavily gains `extract(self, urls, query=None, extract_depth="basic")` (records calls, returns scripted or []).
- [ ] **Step 4: Run full suite → PASS.**
- [ ] **Step 5: Commit** — `feat: re-check verifies against full extracted pages, not just snippets`

### Task 5: Time-ranged freshness probe

**Files:**
- Modify: `backend/app/watcher.py:23-36` (probe_changed)
- Test: `backend/tests/test_watcher.py`

**Interfaces:**
- Produces: probe search becomes `tavily.search(watch["topic"], max_results=5, role="probe", time_range="week")` — only content from the last week counts as "new", so old-indexed pages stop triggering false delta runs. Topic stays GENERAL (`topic=news` biases against technical blogs → false no-change; deviation from initial verdict, ledgered). Exclusion filter unchanged (Task: trust_multiplier semantics).

- [ ] **Step 1: Failing test**
```python
async def test_probe_time_ranged_and_role(memory):        # FakeTavily.kwargs[-1] has time_range="week"; snapshot tavily_probe == 1 after probe
```
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** one-line change.
- [ ] **Step 4: Run full suite → PASS.**
- [ ] **Step 5: Commit** — `feat: freshness probe time-ranged (last week) with own telemetry role`

### Task 6: Telemetry panel + README + DECISIONS

**Files:**
- Modify: `frontend/src/components/TelemetryPanel.jsx` (probe + extract lines in role split), `README.md` (Tavily section: 6 roles; explicit "Tavily never reasons — no /research, no include_answer" line), `docs/DECISIONS.md` (pass rulings incl. `/research` rejection rationale + probe topic deviation)

- [ ] **Step 1: TelemetryPanel** — render `tavily_probe`, `tavily_extracts` next to existing role split; `npm run build`.
- [ ] **Step 2: README** — Tavily paragraph: grounding · prosecution · community prosecution · re-check · time-ranged probe · full-page extract; budget line example updated.
- [ ] **Step 3: DECISIONS.md** — new section: Tavily depth pass rulings (incl. `/research`+`include_answer` rejection rationale, probe topic deviation, and the chunks ruling: no code change — Tavily search already returns query-reranked content chunks by default; our 800-char caps stay the deterministic gate).
- [ ] **Step 4: Commit** — `docs: Tavily depth pass — six roles, no black-box research`

## Verification (whole pass)

1. `cd backend && python -m pytest tests/ -q` — full suite green (target ≥152).
2. `cd frontend && npm run build` — passes.
3. Live smoke (keys in `.env`): run with profile trusted+excluded domains set → done-event telemetry shows role split incl. probe; force a delta run → check re-vote evidence carries FULL PAGE blocks; watch probe cycle → `tavily_probe` increments.
