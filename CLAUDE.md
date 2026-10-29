# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Vera** — personal deep research agent ("research that knows you, and proves it"). Entry for the Nebius x NVIDIA Global AI Hackathon, **Personal AI track**, submissions close **Oct 30, 2026 10:00am PDT**.

Hard submission constraints (verified from the Devpost rules — never violate):
- All LLM inference via **Nebius Token Factory** (`https://api.tokenfactory.nebius.com/v1`, OpenAI-compatible)
- Use ≥1 **NVIDIA open source model** (Nemotron is the planner/synthesizer); verifiers use 2+ other catalog models
- Web search exclusively via **Tavily** API (also targets the separate "Best Use of Tavily" prize)
- Public repo with Apache 2.0 license; README must explicitly document NVIDIA model + Token Factory usage

## Status & Plan

As of 2026-10-30 the build + claim-integrity + budget-enforcement + Personal-AI add-ons + shine pass (verdict transparency) + Tavily depth pass (search-side trust via prefer/exclude, community prosecution, full-page extract on re-check, time-ranged probe) + mode upgrades (run provenance `manual|delta|skill|watch`, watch re-freeze `PUT /api/watch/{id}`, exponential watch error backoff capped 16×) are complete: 175/175 backend tests green, frontend builds. Live-verified per-run numbers (bullet brief): 16/20 search budget, 120K tokens (−71% vs unbounded), 10 claims, 211 report words, 12 unused sources surfaced, coverage gate honored all 4 bullets. Models pinned in `.env`: planner `nvidia/nemotron-3-super-120b-a12b`, verifiers `deepseek-ai/DeepSeek-V4-Pro` + `Qwen/Qwen3-235B-A22B-Instruct-2507`.

Key docs: **`docs/DECISIONS.md`** — every design decision + build ruling with rationale (read before changing planner/verifier/budget logic). Build plans: `docs/superpowers/plans/` (2026-10-27 main build; 2026-10-29 track-completion, personal-ai-addons, shine-pass, tavily-depth; 2026-10-30 blur-fixes, mode-upgrades).

Known machine quirk: Avast TLS interception breaks Python `ssl` — `truststore.inject_into_ssl()` shim in `app/main.py` handles it; don't remove.

Remaining: host demo URL (set `DAILY_TOKEN_BUDGET` first), record <3min YouTube video, devpost submission (deadline Oct 30, 10:00am PDT).

Design decisions locked (do not relitigate): Personal AI track; differentiation = user context model + research memory with delta mode + per-source trust (all existing open-source deep-research repos are stateless); moat = adversarial cross-model claim verification (impossible with a single model — the sponsor constraint is the product).

## Commands (after scaffolding — see plan Tasks 1 & 13)

```powershell
# Backend
cd backend
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest tests/ -v                # all tests
python -m pytest tests/test_verifier.py -v   # single file
python -m pytest tests/test_llm.py::test_name -v   # single test
uvicorn app.main:app --reload             # dev server

# Frontend
cd frontend
npm install
npm run dev                               # dev server
npm run build                             # verify build passes
```

## Architecture

```
brief ─► [1 Planner] ─► [2 Searcher] ─► [3 Drafter] ─► [4 Verifier] ─► [5 Synthesizer] ─► report
              ▲              │              │             │                      │
        user profile    Tavily ×N      claims+citations   2+ models              persona
        + memory        trust filter   (atom+cite URLs)   adversarial verdicts   voice + delta
        (SQLite)                                          + Tavily re-check
```

- **Backend** `backend/app/`: FastAPI; `pipeline/` holds one async function per stage. Every stage takes its clients (`TokenFactoryClient`, `TavilyClient`) as injectable parameters — tests use fakes from `tests/conftest.py`, never real API calls.
- **Verifier** is the core: each claim is cross-examined by every verifier model; if not all agree "supported", Tavily re-searches and models re-check with `web_checked=True`. Resolution: all supported → supported; any contradicted → contradicted; mixed → disputed. Verdicts carry `votes` (per-model verdict+reason of the final round) and `prosecution` (≤800 chars counter-evidence) — surfaced in the report's claim proofs so the adversarial fight is visible.
- **Memory** (`memory.py`, SQLite `vera.db`): user profile (persona, trusted/excluded source domains), runs, verdicts, feedback, topic reports, watches (with `last_digest`), notes, skills. Delta mode = planner receives the prior report for the same `topic_key` and focuses on what changed.
- **Budget enforcement (deterministic, code-owned)**: `app/budget.py` `SearchBudget` caps Tavily searches per run (`min(12 + 2×requirements, 40)`; prose → 20), consumed in priority order searcher → prosecutor → re-checks; exhaustion degrades visibly ("budget-limited"), never crashes. `app/brief.py` `parse_requirements` extracts bullets/numbered items by regex; the orchestrator's coverage gate retries the planner on missed requirements and renders a "Not investigated" report section if still uncovered. Evidence fed to models is capped (top-8 sources × 800 chars); report prose capped (≤120 words/section, ≤8 open questions/changes). Fetched-but-uncited sources surface as the report's clickable "unused sources" section.
- **Privacy gate** (`app/privacy.py`): every Tavily dispatch (searcher, prosecutor, re-check) passes through `safe_query` — word-4-gram overlap with private notes (plus distinctive-token rule for short queries) replaces a leaking query with the topic slug. `scan_for_secrets` warns loudly at note save, never blocks. Honest scope: verbatim note text + short echoes blocked; paraphrases may evade.
- **Watcher** (`app/watcher.py`): in-app scheduler loop (FastAPI lifespan; `WATCH_INTERVAL_MINUTES` env, 0=off). Due watch (interval × `2^min(error_count,4)` backoff after failures) → 1-search freshness probe (role=probe, `time_range="week"` scaled: intervals >168h probe all-time; excluded domains filtered) → delta run (`source="watch"`) → status + digest stored on the watch row; operator webhook (`DIGEST_WEBHOOK_URL`, injected via `create_app`) gets the digest, failures logged not fatal. Watcher failure isolated per watch. Watches editable in place (`PUT /api/watch/{id}`); runs carry provenance (`source`: manual/delta/skill/watch) shown in the memory panel.
- **Events/telemetry**: each run emits SSE stage events (`planning|searching|drafting|verifying|synthesizing|done|error`); process-wide counters (`tf_calls`, `tf_tokens`, `tavily_queries`, `claims_verified`) surface in a `/api/telemetry` endpoint and a frontend panel; the `done` event carries a per-run `run_summary` (searches used/budget, tokens, claims, reused). Sponsor telemetry visibility is a deliberate scoring strategy — keep it prominent.
- **Frontend** `frontend/`: Vite React, consumes SSE via EventSource. Sample brief pre-filled for 1-click judge demo.

## Environment

`.env` at repo root (gitignored). Keys: `TOKEN_FACTORY_API_KEY`, `TAVILY_API_KEY`, `TOKEN_FACTORY_BASE_URL`, `PLANNER_MODEL`, `VERIFIER_MODELS` (comma-separated). Note: the original `.env` held Tavily's key as `Tavily_API: <value>` (colon separator) — the normalized form is `TAVILY_API_KEY=<value>`; never delete the user's file, only add normalized keys.

## Working Rules

- TDD per the superpowers plugin: failing test → implement → pass → commit, one commit per task.
- Scope guard: no auth/accounts, no PDF export, no multi-language, no chat-sidebar features. Memory serves the single research journey only.
- Never commit `.env` or `vera.db`.
