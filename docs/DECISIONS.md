# Vera — Decision Log

Key decisions, their reasoning, and the trade-offs accepted. Newest last.

## Ideation (2026-10-27)

- **Hackathon**: Nebius x NVIDIA Global AI Hackathon, **Personal AI track**. Deadline Oct 30, 10:00am PDT.
- **Why Vera exists**: surveyed 9 open-source deep-research repos (gpt-researcher ~30K★, HF smolagents ~24K★, Alibaba DeepResearch ~20K★, langchain open_deep_research ~10K★, local-deep-research ~8.7K★…). Two field-wide gaps: all stateless (no user model, no memory), all weak on citation quality. Vera = personal deep research: knows you, remembers past research, adversarially verifies every claim.
- **Rejected ideas** (scored on P-I-T-C-H, threshold 21/25): ReSight (AI-visibility audit — commercial category already exists), CrossCheck (multi-model consensus — became a subsystem, not the product), AgentReadiness (agent-usability audit — browser-automation demo risk), Slack research concierge (one-prompt-veto), open Devin rival (crowded, flaky demos), personal chief-of-staff (Frankenstein scope), model router platform (no judge wow).
- **Moat**: adversarial cross-model claim verification — structurally impossible with a single-model API. The sponsor constraint (Nebius Token Factory + NVIDIA open models) IS the product engine. Tavily is the referee (also targets the $3k Best-Use-of-Tavily prize).

## Build rulings (chronological, from the execution ledger)

- **Model IDs live on the LLM client** (`planner_model`/`drafter_model`/`verifier_models` attrs, injected from Settings in `main.py`) — keeps orchestrator signatures clean. Cost: constructor churn if schema changes.
- **Memory runs keyed by `run_uuid`** (not int id) — the API generates the uuid before the report exists; SSE + report + feedback all key on it.
- **`ResearchReport.claim_verdicts` + `claim_proofs` maps** — UI badges and clickable proofs need per-claim verdicts; plan originally had only summary counts.
- **`telemetry.py` pulled into Task 3** — llm.py increments counters from the start; Task 11 only wires events.
- **No `response_format` json_schema — EVER.** Token Factory garbles structured output on Nemotron-3 reasoning models (`{"sub_questions":[{"id":", ","text":""}]}`). Schema goes into the prompt; JSON extracted by brace-finding with one retry. Cost: models that honor response_format lose nothing — prompt shaping suffices.
- **`truststore.inject_into_ssl()` shim in `main.py`** — Avast TLS interception on the dev machine breaks Python's ssl for httpx. Harmless elsewhere; do not remove.
- **4096-token default for JSON calls** — claim-list JSON truncated at 2000.
- **Drafter evidence trim (1200→800 chars) + top-8 sources per sub-question** — "read narrow": output has a word cap, so input gets one too.
- **Verifier**: prosecutor pass (hunt refutation via Tavily BEFORE voting) + cross-model vote + disagreement-triggered web re-check. Resolution: all supported → supported; any contradicted → contradicted; else disputed.
- **TaskGroup containment** (searcher + verifier) — a stage failure cancels sibling LLM/Tavily calls instead of orphaning them.
- **SSE replay buffer** — per-run event list + queue under a per-run lock; late subscribers (the normal path for fast-fail runs) replay stored events then go live. Subscribers unregister on disconnect.
- **Background run tasks registered in `app.state.background_tasks`** — asyncio only holds weak refs to bare `create_task` runs.
- **Empty/`<2` `VERIFIER_MODELS` refuses to start** — empty verifier list silently auto-supported every claim (`all([]) == True`).
- **Drafter cap: 5 load-bearing claims per sub-question** — first live run drafted 84 claims (drafter greed, no cap); report noise + 4× verify cost. Now ~10-35.
- **Claim-integrity pass (2026-10-27/28)** — audit found claims overclaimed vs shipped; directive: make claims true, don't reword. Added: profile substance (role/goals/expertise → planner prompt + UI), feedback loop closure (👎 claim texts raise verifier strictness on future runs), fuzzy topic match for delta, true delta (reused sub-questions skip search/draft/verify), clickable verdict proofs.
- **Budget enforcement (2026-10-28)** — deterministic, code-owned, never prompt-hoped:
  - `SearchBudget`: `min(12 + 2×requirements, 40)` searches/run (prose brief → 20). Priority: searcher → prosecutor → re-checks. Exhaustion degrades visibly (`budget-limited` notes, budget-limited sub-questions), never crashes.
  - Output caps: ≤120 words/section (+400 max_tokens backstop), ≤8 open questions, ≤8 changes, ≤8 sub-questions, bullets parsed by regex (`app/brief.py`), max 12 requirements.
  - Brief coverage gate: every parsed bullet must map to sub-questions; miss → one planner retry with missed list injected; still missed → "Not investigated" report section. LLM cannot silently drop requirements.
  - **Unused-sources section**: fetched-but-uncited sources (≤30) listed with links at report bottom — trust-excluded domains never shown. Zero extra searches.
- **`DAILY_TOKEN_BUDGET` env** — hosted-demo protection: 429 when exhausted (process restarts reset it).
- **Live measured impact** (bullet brief, 4 requirements): searches 45→16/20, tokens 411K→120K (−71%), calls 189→67, claims 84→10, prose ~4 pages→211 words; verdict spread healthier (6 supported / 2 contradicted / 2 disputed vs 81/3 skew).

## Deliberately out of scope

Auth/accounts, PDF export, multi-language, chat-sidebar/history UI, Chrome extension, agent "modes", Physical AI track. Memory serves the single research journey only.

## Submission artifacts remaining

Hosted demo URL (set `DAILY_TOKEN_BUDGET` first), <3-min YouTube video, devpost submission.
