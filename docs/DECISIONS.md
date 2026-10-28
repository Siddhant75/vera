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

## Add-ons build rulings (2026-10-29)

- **Private notes privacy gate is deterministic** (`app/privacy.py` `safe_query`): every Tavily dispatch (sub-question, prosecutor, re-check) checked for word-4-gram overlap with note content; leaking query replaced by topic slug. Prompt-level instruction to the planner is defense-in-depth only — the code gate is the guarantee.
- **Secrets scan = warn-and-save** (`scan_for_secrets`): API-key/password/private-key/card patterns produce loud save-time warnings; never silently blocked (user autonomy). Never-paste list shown in UI + README.
- **Notes are topic-keyed and capped** (5/topic, 10k chars, oldest evicted); injected into planner+drafter prompts only for their topic; never rendered into unused-sources or exports.
- **Webhook digest = operator-set env URL only** (`DIGEST_WEBHOOK_URL`) — never accepted from API input (SSRF-safe). Delivery failure = logged, watch still completes as `changed`; delivery is inbound-to-you only — Vera never auto-posts/publishes on a user's behalf.
- **Webhook digest delivered after `changed` watch runs** — payload = topic + ≤8 changes + verdict summary; delivery failure logged, watch status unaffected (digest is a bonus, never a blocker).
- **Purge-all wipes everything** (runs, verdicts, sources, feedback, watches, notes, skills — including profile): "delete my data" must mean all of it. Watcher loop tolerates the empty state.

## Planned next (approved 2026-10-28, not yet built)

- **Task 24 — Topic Watch (the track's "always-on")**: watched-topics table + in-app scheduler; due topic → automatic delta run → changes digest. Watcher failure = logged + retried next cycle (last missing fallback). Token cost ≈ $0.10-0.30/topic/day, inside DAILY_TOKEN_BUDGET.
- **Task 25 — Skills (reusable, honest)**: named recipes = persona + brief template + topic + source prefs; CRUD + one-click run.
- **Task 26 — Deployment**: frontend → Vercel; backend container → Render/Railway/fly.io free tier (Dockerfile); Nebius Serverless Endpoint/Job documented as optional sponsor-surface path. README labels honestly: "AI inference on Nebius Token Factory; demo hosted on Vercel/Render".
- **Tavily prize upgrades**: role-labeled Tavily telemetry + README "How Tavily powers Vera" section.

## Deliberately out of scope

Auth/accounts, PDF export, multi-language, chat-sidebar/history UI, Chrome extension, agent "modes", Physical AI track. Memory serves the single research journey only.

## Track-fit + hosting + Tavily strategy (2026-10-28)

- **Named track tools are NOT compulsory.** Verified across three sources (official-rules summaries, hackathon recaps): the rule is "runs on Nebius Token Factory / AI Cloud + ≥1 NVIDIA open model + genuinely fits a track". The track paragraph's "use tools such as NemoClaw, OpenShell, Hermes Agent, and Nebius Serverless" is exemplary ("such as"), not a checklist. NemoClaw/OpenShell/Hermes Agent dropped by user decision; Serverless retained as optional.
- **Track retained: Personal AI** (re-checked against all four track texts). Best Apps and Agents also viable but broader field and less differentiated; Coding/Agentic skews dev-tooling; Physical AI impossible without hardware. Persistent memory — the track paragraph's first named feature — is Vera's headline subsystem.
- **Demo hosting on Vercel/Render is compliant.** The submission clause is platform-neutral ("URL to a working demo, hosted application, or test build") and the hackathon credits cover only Token Factory + Tavily — no AI Cloud hosting credits exist, so requiring Nebius hosting would be incoherent. Compliance anchor: all model inference runs on Token Factory. Residual ~10% strict-reading risk; mitigation: optional Nebius Serverless Endpoint path (CPU, documented, not primary). Backend needs a real container (SSE + background scheduler + SQLite) → Render/Railway/fly.io free tier, not Vercel functions; frontend on Vercel.
- **Best Use of Tavily ($3k) strategy**: Tavily already used in 4 distinct roles — grounding (per-sub-question), prosecution (refutation hunting), refereeing (disagreement re-checks), transparency (unused-sources pool). No surveyed competitor uses more than one. Upgrades: role-labeled Tavily telemetry (`8 grounding · 6 prosecution · 2 re-check`) + README "How Tavily powers Vera" section aimed at the Tavily judges on the panel.

## Submission artifacts remaining

Hosted demo URL (set `DAILY_TOKEN_BUDGET` first), <3-min YouTube video, devpost submission.
