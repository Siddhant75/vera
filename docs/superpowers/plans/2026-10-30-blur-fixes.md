# Blur Fixes Implementation Plan (prompted vs automated mode boundary)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the skill-run profile swap (the only real blur between user-prompted and Vera-initiated research) and document the frozen-watch-brief + notes-fuzzy-match semantics.

**Architecture:** Skills stop mutating the stored profile. Per-run overrides flow explicitly: `ResearchIn` gains optional `trusted_sources`/`excluded_sources`; `run_research` gains optional `domain_prefs` (orchestrator builds from profile only when not overridden). Skill persona was ALREADY passed explicitly to `run_research` — the swap was redundant for the run and only leaked into later behavior.

**Tech Stack:** Existing FastAPI/pydantic patterns; no new deps.

**Spec:** Session verdict 2026-10-30 — three blur points: (1) skill-run profile swap leaks (fix), (2) watch briefs never re-freeze (document), (3) notes match by fuzzy topic key, differently-phrased watch topics may miss (document).

## Global Constraints

- Tavily = only search; all LLM via Token Factory. Tests use fakes; never real API calls.
- Deterministic gates stay code-owned: domain prefs still normalized via `clean_domains`, caps unchanged.
- Never commit `.env` or `vera.db`.

## Review Focus

1. **Restore race** — the swap-and-restore alternative was rejected precisely because `post_research` returns before the background run reads the profile; the no-swap design must leave NO stored-profile mutation anywhere in the skill path. Pinned by `test_skill_run_leaves_profile_untouched`.
2. **Override precedence** — explicit `domain_prefs` must win over profile-built prefs; absent/None must fall back to profile. Pinned in orchestrator test.
3. **Persona source for skill runs** — skill persona reaches the run via `ResearchIn.persona` (explicit), NOT via profile. Pinned by planner-prompt assertion.

---

### Task 1: No-swap skill runs — per-run source-prefs override

**Files:**
- Modify: `backend/app/main.py` (`ResearchIn`, `run_skill`), `backend/app/pipeline/orchestrator.py` (`run_research` signature)
- Test: `backend/tests/test_skills_v2.py`, `backend/tests/test_orchestrator.py`

**Interfaces:**
- `ResearchIn` gains `trusted_sources: list[str] | None = None`, `excluded_sources: list[str] | None = None`.
- `run_research(run_id, brief, persona, topic, delta, llm, tavily, memory, emit, domain_prefs: dict | None = None)` — `domain_prefs = domain_prefs or {"trusted": clean_domains(profile...), "excluded": ...}` (explicit wins).
- `run_skill`: deletes `prev = memory.get_profile()` + the `set_profile(...)` swap entirely; passes `ResearchIn(brief, topic, persona=skill["persona"], trusted_sources=skill["trusted_sources"], excluded_sources=skill["excluded_sources"])`.
- `post_research` passes `r.trusted_sources`/`r.excluded_sources` through (None when absent → orchestrator falls back to profile).

- [ ] **Step 1: Failing tests**
```python
# test_skills_v2.py — replace the swap assertion in test_skill_run_preserves_profile_context:
def ... :
    await run skill
    p = m.get_profile()
    assert p["role_context"] == "CTO of 10-person startup"
    assert p["persona"] == "founder"          # FLIPPED: skill run must not touch stored profile
    assert p["trusted_sources"] == []
# new:
async def test_skill_run_uses_skill_sources_without_profile_mutation(tmp_path):
    # skill with trusted_sources=["skill-src.com"]; run; profile trusted_sources stays [];
    # FakeTavily kwargs show include_domains=["skill-src.com"]
# test_orchestrator.py:
async def test_explicit_domain_prefs_win_over_profile(tmp_path):
    # profile trusted=["profile.com"]; run_research(domain_prefs={"trusted": ["explicit.com"], "excluded": []})
    # -> FakeTavily kwargs include_domains == ["explicit.com"]
```
- [ ] **Step 2: Run → FAIL** (profile mutated / TypeError on kwarg).
- [ ] **Step 3: Implement** the three files.
- [ ] **Step 4: Full suite → PASS.**
- [ ] **Step 5: Commit** — `fix: skill runs stop mutating the profile — per-run source-prefs override`

### Task 2: Document the mode boundary

**Files:** `docs/DECISIONS.md`, `README.md` (Track section: watches freeze brief+persona at creation; memory/trust/notes/feedback read live; notes match by topic key — differently-phrased watch topics may miss their notes)

- [ ] **Step 1: DECISIONS** — new "Mode boundary" section: prompted vs automated table rationale, no-swap ruling, frozen-brief ruling (predictability), fuzzy-note scope.
- [ ] **Step 2: README** — two honest lines in Track section.
- [ ] **Step 3: Commit** — `docs: prompted vs automated mode boundary`

## Verification

1. `cd backend && python -m pytest tests/ -q` — full suite green.
2. `npm run build` — passes.
