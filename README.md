# Vera — Research that knows you, and proves it.

> Deep research tools give every user the same stateless answer and cite sources nobody checked.
> Vera remembers who you are and what you already researched, then adversarially verifies every single claim across multiple NVIDIA open models before it reaches you.

## ⚡ 30-Second Quickstart

- **Live Demo:** [demo URL — see submission form]
- **Demo Video:** [YouTube link — see submission form]
- **Try the 1-Click Sample:** run the backend and frontend, click **Run Research** — the sample brief ("Kubernetes or serverless for our ML inference API?") is pre-filled. Then tag the topic and click **Run Delta** to see only what changed.

```bash
# backend
cd backend && python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
# put TOKEN_FACTORY_API_KEY + TAVILY_API_KEY in ../.env (see .env.example)
uvicorn app.main:app --reload

# frontend (second terminal)
cd frontend && npm install && npm run dev
```

## 🚀 Deployment & Ops

**One-click deploy:** this repo ships a [`render.yaml`](render.yaml) blueprint — Render dashboard → New → Blueprint → point at the repo → paste your keys. Backend (Python + uvicorn) and frontend (static) deploy from one file; Render auto-deploys on every push. No Dockerfile needed for this stack; GitHub Actions unnecessary since Render builds on push. Free-tier note: SQLite is ephemeral (memory resets on spin-down); add a paid disk + `DB_PATH=/var/data/vera.db` for persistence. (Render's API/CLI requires a card on file — the dashboard route does not.)

**Public demo posture** (what's on/off on the deployed demo):
- Watcher loop **off** (`WATCH_INTERVAL_MINUTES=0`) — watches can be created, edited, and viewed, but nothing runs automatically. Always-on is an operator choice: set the env to e.g. `30` on your own instance.
- Watch slots capped (`MAX_WATCHES=5`) and a process-lifetime token ceiling (`DAILY_TOKEN_BUDGET=2000000`) — exhausting it returns a clear 429, and the free-tier spin-down/restart resets it.
- **Bring your own keys:** run locally (`.env`, see Quickstart) or deploy your own blueprint instance — then everything runs against your Token Factory + Tavily accounts, which is the intended mode for a *personal* assistant anyway.

**Always-on in practice:** Vera never burns LLM tokens idling — the watcher probes each due topic with 1 Tavily search and only wakes the models when content actually changed; failing watches back off exponentially. A watch that produced a run shows up with a `watch` badge in the activity log.

## 📋 How to Use Vera (60 seconds)

1. **Run Research** — the sample brief is pre-filled; click once and watch the pipeline go: plan → search → draft → verify → report.
2. **Make it yours** — set your persona (engineer/founder/analyst) and role context; every sub-question and the report voice adapt to you.
3. **Give it private context** — add a note on the topic ("we're bound to k8s by a platform mandate"); it steers the research and the report tells you how many notes it considered — never what they said.
4. **Prove it** — expand any claim badge: see each model's individual vote and the prosecutor's counter-evidence. Run the same topic again with **Run Delta** to get only what changed.
5. **Automate it** — watch a topic; when the web changes, Vera re-researches and leaves a digest in the activity log (tagged `watch`). Skills (⚙ named recipes) run with one click, with template variables.

**Bring your own keys:** copy `.env.example` → `.env`, add your [Nebius Token Factory](https://build.nebius.com/) + [Tavily](https://tavily.com/) keys, pick models (`PLANNER_MODEL`, `VERIFIER_MODELS`), run. The public demo runs on our keys under a hard budget; your instance runs on yours.

## 💡 The Problem & The Insight

- Every open-source deep-research agent (gpt-researcher, smolagents, open_deep_research…) is **stateless**: same brief, same generic report, no memory of you or past research.
- Field-wide **citation quality is broken** — claims cite sources nobody verified, or nothing at all.
- Vera's insight: treat **model disagreement as a feature**. One model hallucinating is a bug; several open models disagreeing on a claim is a *detectable signal* — and only possible on open multi-model infrastructure.

## 🚀 How It Works (The Magic)

1. **Plan** — Nemotron decomposes your brief into sub-questions phrased for your persona (engineer/founder/analyst), or for *what changed* if you researched this topic before.
2. **Search** — live Tavily web search per sub-question, with your trusted source domains preferred inside the query itself and banned domains excluded at the source.
3. **Draft** — atomic claims extracted from fetched sources; every claim must cite a real fetched URL; uncited claims are dropped, not guessed.
4. **Verify** — a prosecutor pass hunts counter-evidence for every claim (live Tavily refutation search), then 2+ independent models vote on claim + refutation evidence. Disagreement triggers a second web re-check → supported / contradicted / disputed. **Expand any claim to watch the fight: each model's individual vote and the prosecutor's counter-evidence are shown verbatim.**
5. **Synthesize** — persona-voiced report with verdict badges and open questions written back to research memory. Run a delta on the same topic and truly-reused sub-questions skip search/draft/verify entirely — the report shows what changed.

## 🏆 How Nebius Token Factory + NVIDIA Open Models Power This

- **NVIDIA Nemotron** (open source, served on Nebius Token Factory) is the planner and synthesizer — it structures the research and writes your report.
- **Cross-model adversarial verification** requires multiple *different* open models: each claim is judged by 2+ independent Token Factory models against the evidence. This is the product's core and is impossible with a single-model API.
- **Tavily** is not a wrapper here — it plays **six distinct roles**: **grounding** (research per sub-question, with your trusted domains *preferred inside the query* and banned domains excluded at the source), **prosecution** (refutation searches hunting counter-evidence), **community prosecution** (the same hunt restricted to reddit.com — practitioner counter-evidence is a different evidence class), **refereeing** (re-checks when models disagree), **full-page extraction** (on re-check, the claim's own cited pages are extracted so models judge the whole page, not a snippet), and **transparency** (the fetched-but-uncited source pool is published at the bottom of every report — judge the sources yourself). Every budget-consuming call is capped and counted by the per-run budget (example burn: `grounding 8 · prosecution 6 · re-check 2 · extracts 1` of 20) and every role is visible in the telemetry panel; the transparency pool costs nothing extra. Tavily never *reasons*: no `/research` endpoint, no `include_answer` — finding evidence is Tavily's job; thinking is done by NVIDIA open models on Nebius Token Factory.
- The telemetry panel (top of the app) shows the live burn: Token Factory calls/tokens, role-labeled Tavily queries, claims verified — the sponsor infrastructure is the visible engine, not a hidden dependency.

## 🛠️ Architecture & Technical Implementation

```
brief → Planner → Searcher → Drafter → Verifier → Synthesizer → report
          ▲                                    │  ▲
   user profile + memory (SQLite)         Tavily web re-check on disagreement
```

- `backend/app/` — FastAPI; one async stage function per pipeline stage (`app/pipeline/`); clients injected and faked in tests (**178 passing**).
- `backend/app/memory.py` — SQLite: profile, runs (with provenance: manual/delta/skill/watch), verdicts, feedback, topic-keyed reports (delta mode), watches, notes, skills.
- `backend/app/budget.py` + `brief.py` — deterministic search budget (`min(12 + 2×requirements, 40)`, priority-ordered: searcher → prosecutor → re-check → extract) and bullet-requirement parsing with a planner coverage gate ("Not investigated" section instead of silent drops).
- `backend/app/privacy.py` — deterministic privacy gate at every Tavily dispatch site (4-gram + distinctive-token rules); secrets scan warns at note save.
- `backend/app/watcher.py` — always-on loop: probe-gated (1 Tavily search), exponential backoff on failures, digests in-app + webhook.
- `backend/app/skills.py` — reusable recipes with template variables (`{topic}`, `{date}`, `{quarter}` + custom).
- `frontend/src/` — Vite React; SSE live pipeline view, persona toggle, per-claim proof expansion, telemetry panel, memory/activity panel.

## Track

**Personal AI** — an always-on, private research assistant: persistent memory (it knows your role, goals, and past research), reusable research skills, source trust you control, and a topic watcher that keeps researching while you're away. Two modes, one memory: research you *prompt* is shaped in the moment by your persona, notes, and trust settings; research Vera *initiates* (watches) uses a frozen brief and persona but reads your trust, notes, and feedback live — so what you taught it while present still steers what it does while you're away. Watches never spend LLM tokens unless the freshness probe detects real change, failing watches back off instead of burning credits, and every run in memory is tagged with the mode that produced it — the activity log is honest. All model inference runs on **Nebius Token Factory** with **NVIDIA Nemotron** + open models; the demo app is hosted on Vercel/Render (inference compliance is unchanged — every LLM call goes to Token Factory).

## 🔒 Security & Privacy

Vera stores everything locally (SQLite, no accounts, no sync). Private notes attach to topics and inform planning/drafting — every report shows **how many** notes shaped it, never what they said. Watch digests appear in-app and (if the operator sets a webhook) are delivered out. Two hard rules, enforced in code — not by prompt:

- **Verbatim note text never reaches Tavily.** Every search query is checked before dispatch: 4-gram overlap with your notes, or (for short queries) any distinctive-token overlap, replaces the query with the topic slug. Deterministic code gate; paraphrases of note ideas may still evade it — that is why the never-paste list matters.
- **Secrets are warned at save-time, never silently accepted or blocked** — Vera scans for API-key/password/private-key/card-number patterns and tells you loudly.

**Never paste into notes:** passwords, API keys, account numbers, medical records — anything you wouldn't tell a cloud service. Notes live on your machine, but their context is processed by Nebius Token Factory during research. Purge everything anytime from the app ("What Vera remembers" → delete).

## 🔥 Challenges & Accomplishments

- **Structured output garbled** on Token Factory's Nemotron reasoning models (`response_format=json_schema` returned `{"sub_questions":[{"id":", ","text":""}]}`) — so all structured calls use schema-in-prompt + brace extraction, with retries. Lesson: the hackathon's sponsor constraint forced us off conveniences everyone else relies on.
- **Verifier greed**: the first live run drafted 84 claims — we made caps deterministic code (5 claims/sub-question, budgeted searches, evidence caps), not prompt hopes. Measured: 45→16 searches, 411K→120K tokens (−71%) with better verdict spread.
- **The moat is the constraint**: single-model APIs can't do adversarial multi-model verification. What the rules forbid (one model) is exactly what makes Vera's core work — the sponsor constraint IS the engine.
- **Privacy is code, not prompts**: a deterministic gate sits at every Tavily dispatch site; honestly scoped (verbatim text + short echoes blocked; paraphrases may evade) and documented.

## 🔭 What's Next

- Persistent hosted memory (managed disk or volume) — demo runs on free ephemeral storage today
- Watch run history timeline per topic; skill-linked watches that re-fill template vars each cycle
- Export verified reports (PDF/Markdown) with full proof chains
- Multi-user auth on top of the existing memory-control layer

## License

Apache 2.0 — original implementation; no code from any surveyed open-source deep-research project.
