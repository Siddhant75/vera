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

As of 2026-10-27 the repo is pre-scaffold. The authoritative build document is
`docs/superpowers/plans/2026-10-27-vera.md` — 14 TDD tasks with exact interfaces, executed
via the superpowers plugin (`superpowers:executing-plans` / `superpowers:subagent-driven-development`).
Read it before writing any code: it pins file layout, pydantic schemas, function signatures, and test names.

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
- **Verifier** is the core: each claim is cross-examined by every verifier model; if not all agree "supported", Tavily re-searches and models re-check with `web_checked=True`. Resolution: all supported → supported; any contradicted → contradicted; mixed → disputed.
- **Memory** (`memory.py`, SQLite `vera.db`): user profile (persona, trusted/excluded source domains), runs, verdicts, feedback, topic reports. Delta mode = planner receives the prior report for the same `topic_key` and focuses on what changed.
- **Events/telemetry**: each run emits SSE stage events (`planning|searching|drafting|verifying|synthesizing|done|error`); process-wide counters (`tf_calls`, `tf_tokens`, `tavily_queries`, `claims_verified`) surface in a `/api/telemetry` endpoint and a frontend panel. Sponsor telemetry visibility is a deliberate scoring strategy — keep it prominent.
- **Frontend** `frontend/`: Vite React, consumes SSE via EventSource. Sample brief pre-filled for 1-click judge demo.

## Environment

`.env` at repo root (gitignored). Keys: `TOKEN_FACTORY_API_KEY`, `TAVILY_API_KEY`, `TOKEN_FACTORY_BASE_URL`, `PLANNER_MODEL`, `VERIFIER_MODELS` (comma-separated). Note: the original `.env` held Tavily's key as `Tavily_API: <value>` (colon separator) — the normalized form is `TAVILY_API_KEY=<value>`; never delete the user's file, only add normalized keys.

## Working Rules

- TDD per the superpowers plugin: failing test → implement → pass → commit, one commit per task.
- Scope guard: no auth/accounts, no PDF export, no multi-language, no chat-sidebar features. Memory serves the single research journey only.
- Never commit `.env` or `vera.db`.
