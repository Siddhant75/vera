# Vera — Research that knows you, and proves it.

> Deep research tools give every user the same stateless answer and cite sources nobody checked.
> Vera remembers who you are and what you already researched, then adversarially verifies every single claim across multiple NVIDIA open models before it reaches you.

## ⚡ 30-Second Quickstart

- **Live Demo:** [demo URL — see submission form]
- **Demo Video:** [YouTube link — see submission form]
- **Try the 1-Click Sample:** run the backend and frontend, click **Run Research** — the sample brief ("Kubernetes or serverless for our ML inference API?") is pre-filled. Then tag the topic and click **Run Delta** to see only what changed.

```bash
# backend
cd backend && python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
# put TOKEN_FACTORY_API_KEY + TAVILY_API_KEY in ../.env (see .env.example)
uvicorn app.main:app --reload

# frontend (second terminal)
cd frontend && npm install && npm run dev
```

## 💡 The Problem & The Insight

- Every open-source deep-research agent (gpt-researcher, smolagents, open_deep_research…) is **stateless**: same brief, same generic report, no memory of you or past research.
- Field-wide **citation quality is broken** — claims cite sources nobody verified, or nothing at all.
- Vera's insight: treat **model disagreement as a feature**. One model hallucinating is a bug; several open models disagreeing on a claim is a *detectable signal* — and only possible on open multi-model infrastructure.

## 🚀 How It Works (The Magic)

1. **Plan** — Nemotron decomposes your brief into sub-questions phrased for your persona (engineer/founder/analyst), or for *what changed* if you researched this topic before.
2. **Search** — live Tavily web search per sub-question, weighted by your trusted sources.
3. **Draft** — atomic claims extracted from fetched sources; every claim must cite a real fetched URL; uncited claims are dropped, not guessed.
4. **Verify** — a prosecutor pass hunts counter-evidence for every claim (live Tavily refutation search), then 2+ independent models vote on claim + refutation evidence. Disagreement triggers a second web re-check → supported / contradicted / disputed, with the reason one click away.
5. **Synthesize** — persona-voiced report with verdict badges and open questions written back to research memory. Run a delta on the same topic and truly-reused sub-questions skip search/draft/verify entirely — the report shows what changed.

## 🏆 How Nebius Token Factory + NVIDIA Open Models Power This

- **NVIDIA Nemotron** (open source, served on Nebius Token Factory) is the planner and synthesizer — it structures the research and writes your report.
- **Cross-model adversarial verification** requires multiple *different* open models: each claim is judged by 2+ independent Token Factory models against the evidence. This is the product's core and is impossible with a single-model API.
- **Tavily** is not a wrapper here — it plays **four distinct roles**: **grounding** (research per sub-question), **prosecution** (refutation searches hunting counter-evidence), **refereeing** (re-checks when models disagree), and **transparency** (the full fetched-but-uncited source pool is published at the bottom of every report — judge the sources yourself). A per-run budget bounds and surfaces the burn: `grounding 8 · prosecution 6 · re-check 2` of 20.
- The telemetry panel (top of the app) shows the live burn: Token Factory calls/tokens, role-labeled Tavily queries, claims verified — the sponsor infrastructure is the visible engine, not a hidden dependency.

## 🛠️ Architecture & Technical Implementation

```
brief → Planner → Searcher → Drafter → Verifier → Synthesizer → report
          ▲                                    │  ▲
   user profile + memory (SQLite)         Tavily web re-check on disagreement
```

- `backend/app/` — FastAPI; one async stage function per pipeline stage (`app/pipeline/`); clients injected and faked in tests (51 passing).
- `backend/app/memory.py` — SQLite: profile, runs, verdicts, feedback, topic-keyed reports (delta mode).
- `frontend/src/` — Vite React; SSE live pipeline view, persona toggle, per-claim feedback, telemetry panel.
- Tests: `cd backend && python -m pytest tests/ -v`

## Track

**Personal AI** — an always-on, private research assistant: persistent memory (it knows your role, goals, and past research), reusable research skills, source trust you control, and a topic watcher that keeps researching while you're away. All model inference runs on **Nebius Token Factory** with **NVIDIA Nemotron** + open models; the demo app is hosted on Vercel/Render (inference compliance is unchanged — every LLM call goes to Token Factory).

## 🔒 Security & Privacy

Vera stores everything locally (SQLite, no accounts, no sync). Private notes attach to topics and inform planning/drafting. Two hard rules, enforced in code — not by prompt:

- **Verbatim note text never reaches Tavily.** Every search query is checked before dispatch: 4-gram overlap with your notes, or (for short queries) any distinctive-token overlap, replaces the query with the topic slug. Deterministic code gate; paraphrases of note ideas may still evade it — that is why the never-paste list matters.
- **Secrets are warned at save-time, never silently accepted or blocked** — Vera scans for API-key/password/private-key/card-number patterns and tells you loudly.

**Never paste into notes:** passwords, API keys, account numbers, medical records — anything you wouldn't tell a cloud service. Notes live on your machine, but their context is processed by Nebius Token Factory during research. Purge everything anytime from the app ("What Vera remembers" → delete).

## License

Apache 2.0 — original implementation; no code from any surveyed open-source deep-research project.
