# UX Telemetry & Research Showcase Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform Vera's UI and backend coordination to clearly separate per-run vs. lifetime telemetry, showcase full research draft texts with 1-click export, prominently display rich cited sources and the uncited transparency pool, elevate the adversarial verification moat with controlled proof expansion, and enable interactive memory exploration.

**Architecture:** Extend `ResearchReport` with persisted `run_summary` tracking exact run deltas across Token Factory calls and 6 Tavily roles. Enrich the verification stage with draft claims preview for live pipeline inspection without breaking stage ordering. Upgrade frontend components (`TelemetryPanel`, `ReportView`, `MemoryPanel`, `PipelineView`) and CSS to provide dual-tier telemetry, controlled proof expansion, rich source cards, transparency pool explanation, memory navigation, and full draft text markdown generation.

**Tech Stack:** FastAPI, SQLite, Pydantic v2, React 19, Vite, Oxlint, Pytest.

---

### Task 1: Backend Run Telemetry Persistence & 6-Role Delta Tracking

**Files:**
- Create: `backend/tests/test_telemetry_run.py`
- Modify: `backend/app/models.py:50-64`
- Modify: `backend/app/pipeline/orchestrator.py:22-30,120-132`

**Step 1: Write the failing test**

Create `backend/tests/test_telemetry_run.py`:
```python
import pytest
from app.memory import Memory
from app.pipeline.orchestrator import run_research
from tests.conftest import FakeLLM, FakeTavily

PLAN = {
    "brief": "test brief",
    "persona": "engineer",
    "topic_key": "test",
    "depth": "quick",
    "sub_questions": [{"id": "q1", "text": "What is X?"}],
    "coverage": [{"requirement": "test brief", "sq_ids": ["q1"]}],
}
DRAFT = {"claims": [{"text": "X is fast", "citation_urls": ["https://nvidia.com/x"]}]}
VERDICT_SUP = {
    "verdict": "supported",
    "reason": "verified on nvidia.com",
    "votes": [{"model": "m-v", "verdict": "supported", "reason": "ok"}],
    "prosecution": "",
    "web_checked": False,
}
NARR = {"narrative": "X is fast.", "open_questions": []}


@pytest.mark.anyio
async def test_run_summary_persisted_in_report(tmp_path):
    mem = Memory(str(tmp_path / "test.db"))
    llm = FakeLLM([PLAN, DRAFT, VERDICT_SUP, VERDICT_SUP, NARR], planner_model="m-p", verifier_models=["m-v1", "m-v2"])
    tavily = FakeTavily()
    events = []

    async def emit(e):
        events.append(e)

    report = await run_research("run-123", "test brief", "engineer", "test", False, llm, tavily, mem, emit)

    # 1. report model must contain run_summary with complete metrics
    assert hasattr(report, "run_summary")
    assert isinstance(report.run_summary, dict)
    assert "tf_tokens_run" in report.run_summary
    assert "tf_calls_run" in report.run_summary
    assert "tavily_searches_run" in report.run_summary
    assert "tavily_grounding" in report.run_summary
    assert "claims_verified" in report.run_summary

    # 2. report reloaded from SQLite memory must preserve run_summary
    stored = mem.get_report("run-123")
    assert stored is not None
    assert "run_summary" in stored
    assert stored["run_summary"]["tf_tokens_run"] == report.run_summary["tf_tokens_run"]
    assert stored["run_summary"]["tf_calls_run"] == report.run_summary["tf_calls_run"]
```

**Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_telemetry_run.py -v`
Expected: FAIL (AssertionError: assert False where False = hasattr(report, "run_summary")).

**Step 3: Write minimal implementation**

1. In `backend/app/models.py`:
Add `run_summary: dict = Field(default_factory=dict)` to `ResearchReport`.

2. In `backend/app/pipeline/orchestrator.py`:
Compute complete delta between `t_start` and `t_now` right after `synthesize`:
```python
        from app.telemetry import telemetry
        t_now = telemetry.snapshot()
        run_summary = {
            "searches_used": budget.used,
            "search_budget": budget.limit,
            "tf_tokens_run": t_now["tf_tokens"] - t_start["tf_tokens"],
            "tf_calls_run": t_now["tf_calls"] - t_start["tf_calls"],
            "tavily_searches_run": budget.used,
            "tavily_grounding": t_now["tavily_grounding"] - t_start["tavily_grounding"],
            "tavily_prosecution": t_now["tavily_prosecution"] - t_start["tavily_prosecution"],
            "tavily_recheck": t_now["tavily_recheck"] - t_start["tavily_recheck"],
            "tavily_probe": t_now["tavily_probe"] - t_start["tavily_probe"],
            "tavily_extracts": t_now["tavily_extracts"] - t_start["tavily_extracts"],
            "claims_verified": len(verdicts),
            "claims": len(claims),
            "reused": len(reused_sections),
        }
        report.run_summary = run_summary
        memory.save_run(brief, active_persona, tk, report.model_dump(), run_uuid=run_id, source=source)
        memory.save_verdicts(run_id, [v.model_dump() for v in verdicts])
        memory.save_sources(run_id, [{"url": s.url, "title": s.title} for s in sources])
        await emit({"run_id": run_id, "stage": "done", "payload": {"report": report.model_dump(), "run_summary": run_summary}})
        await emit({"run_id": run_id, "stage": END, "payload": {}})
        return report
```

**Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_telemetry_run.py -v`
Expected: PASS.
Run entire backend test suite: `.venv\Scripts\python.exe -m pytest backend/tests`
Expected: 201 passed.

**Step 5: Commit**

```bash
git add backend/app/models.py backend/app/pipeline/orchestrator.py backend/tests/test_telemetry_run.py
git commit -m "feat(telemetry): Persist per-run telemetry delta inside ResearchReport"
```

---

### Task 2: Backend Stage Verification Payload Enrichment & Pipeline View Preview

**Files:**
- Create: `backend/tests/test_drafter_preview.py`
- Modify: `backend/app/pipeline/orchestrator.py:94-96`
- Modify: `frontend/src/components/PipelineView.jsx:38-42`

**Step 1: Write the failing test**

Create `backend/tests/test_drafter_preview.py`:
```python
import pytest
from app.memory import Memory
from app.pipeline.orchestrator import run_research
from tests.conftest import FakeLLM, FakeTavily

PLAN = {
    "brief": "test brief",
    "persona": "engineer",
    "topic_key": "test",
    "depth": "quick",
    "sub_questions": [{"id": "q1", "text": "What is X?"}],
    "coverage": [{"requirement": "test brief", "sq_ids": ["q1"]}],
}
DRAFT = {"claims": [{"text": "X is fast", "citation_urls": ["https://nvidia.com/x"]}]}
VERDICT_SUP = {"verdict": "supported", "reason": "ok", "votes": []}
NARR = {"narrative": "X is fast.", "open_questions": []}


@pytest.mark.anyio
async def test_verifying_stage_carries_draft_claims_preview(tmp_path):
    mem = Memory(str(tmp_path / "test.db"))
    llm = FakeLLM([PLAN, DRAFT, VERDICT_SUP, VERDICT_SUP, NARR], planner_model="m-p", verifier_models=["m-v"])
    tavily = FakeTavily()
    events = []

    async def emit(e):
        events.append(e)

    await run_research("run-125", "test brief", "engineer", "test", False, llm, tavily, mem, emit)

    verifying_events = [e for e in events if e.get("stage") == "verifying"]
    assert len(verifying_events) == 1
    payload = verifying_events[0]["payload"]
    assert "draft_claims" in payload
    assert len(payload["draft_claims"]) == 1
    assert payload["draft_claims"][0]["text"] == "X is fast"
    assert payload["draft_claims"][0]["citations"] == ["https://nvidia.com/x"]
    # Verify stages order is strictly preserved
    stage_names = [e["stage"] for e in events if e.get("stage") != "__end__"]
    assert stage_names == ["planning", "searching", "drafting", "verifying", "synthesizing", "done"]
```

**Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_drafter_preview.py -v`
Expected: FAIL (KeyError: 'draft_claims').

**Step 3: Write minimal implementation**

1. In `backend/app/pipeline/orchestrator.py`:
Enrich the `verifying` stage payload without changing stage sequence:
```python
        stage["current"] = "verifying"
        await emit({"run_id": run_id, "stage": "verifying", "payload": {
            "claim_count": len(claims),
            "draft_claims": [{"text": c.text, "citations": c.citation_urls} for c in claims],
        }})
```
2. In `frontend/src/components/PipelineView.jsx`:
Show the live draft claims preview under the Verifying stage:
```jsx
            {key === "verifying" && payload && (
              <div className="stage-detail">
                <div>{payload.claim_count} claims under cross-examination</div>
                {payload.draft_claims?.length > 0 && (
                  <ul className="stage-claims-preview">
                    {payload.draft_claims.slice(0, 3).map((c, idx) => (
                      <li key={idx}>“{c.text}”</li>
                    ))}
                    {payload.draft_claims.length > 3 && (
                      <li className="muted">+{payload.draft_claims.length - 3} more claims</li>
                    )}
                  </ul>
                )}
              </div>
            )}
```

**Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_drafter_preview.py -v`
Expected: PASS.
Run entire backend test suite: `.venv\Scripts\python.exe -m pytest backend/tests`
Expected: 202 passed.
Run frontend check: `cd frontend && npm run lint && npm run build`
Expected: 0 errors.

**Step 5: Commit**

```bash
git add backend/app/pipeline/orchestrator.py backend/tests/test_drafter_preview.py frontend/src/components/PipelineView.jsx
git commit -m "feat(pipeline): Stream draft claims preview in verifying stage payload"
```

---

### Task 3: Frontend Dual-Tier Telemetry Panel & Memory Sync

**Files:**
- Modify: `frontend/src/components/TelemetryPanel.jsx`
- Modify: `frontend/src/App.jsx:26-32,41-47,88,119-124`
- Modify: `frontend/src/App.css:57-79`

**Step 1: Implement dual-tier display in `TelemetryPanel.jsx`**

Guard against empty objects `{}` or undefined properties:
```jsx
import { useEffect, useState } from "react";
import { getTelemetry } from "../api";

export default function TelemetryPanel({ runSummary }) {
  const [lifetime, setLifetime] = useState(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const t = await getTelemetry();
        if (alive) setLifetime(t);
      } catch { /* backend not up yet */ }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const hasRunSummary = runSummary && (
    runSummary.tf_tokens_run !== undefined ||
    runSummary.tf_calls_run !== undefined ||
    runSummary.searches_used !== undefined
  );

  return (
    <div className="telemetry-bar">
      <div className="telemetry-section run-tier">
        <span className="telemetry-tag run">⚡ This Run</span>
        {hasRunSummary ? (
          <span className="telemetry-detail">
            <b>{runSummary.tf_calls_run || 0} calls</b> / <b>{(runSummary.tf_tokens_run || 0).toLocaleString()} tokens</b> (Token Factory) ·{" "}
            <b>{runSummary.tavily_searches_run || runSummary.searches_used || 0} searches</b> (Tavily: {runSummary.tavily_grounding || 0} grounding, {runSummary.tavily_prosecution || 0} prosecution, {runSummary.tavily_recheck || 0} re-check) ·{" "}
            <b>{runSummary.claims_verified || runSummary.claims || 0} verified claims</b>
          </span>
        ) : (
          <span className="telemetry-detail muted">Ready for research (typical run: 49k–120k tokens)</span>
        )}
      </div>
      {lifetime && (
        <div className="telemetry-section lifetime-tier">
          <span className="telemetry-tag session">🌐 Session Total</span>
          <span className="telemetry-detail">
            <b>{lifetime.tf_calls} calls</b> / <b>{(lifetime.tf_tokens || 0).toLocaleString()} tokens</b> ·{" "}
            <b>{lifetime.tavily_queries} searches</b> · <b>{lifetime.claims_verified} claims verified</b> across all runs
          </span>
        </div>
      )}
    </div>
  );
}
```

**Step 2: Update `App.jsx` to synchronize `runSummary` & remove redundant inline strip**

1. On mount:
```javascript
  useEffect(() => {
    getLastRunReport().then(({ report: rep, runId }) => {
      if (rep && !rep.error && !report) {
        setReport(rep);
        setRestoredRunId(runId);
        if (rep.run_summary) setRunSummary(rep.run_summary);
      }
    }).catch(() => {});
  }, []);
```
2. Pass `runSummary={runSummary || report?.run_summary}` to `<TelemetryPanel />`.
3. Remove the redundant unstyled `<div className="run-summary">` from `App.jsx` (lines 119-124).

**Step 3: Update CSS in `App.css`**

Add machined telemetry strip styles using `--chrome-2`, `--border`, `--text`, and `--mono`:
```css
.telemetry-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border: 1px solid var(--border);
  background: var(--chrome-2);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 18px;
  font-family: var(--mono);
  font-size: 12px;
}
.telemetry-section {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.telemetry-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.telemetry-tag.run {
  background: rgba(76, 187, 138, 0.15);
  color: var(--green);
  border: 1px solid rgba(76, 187, 138, 0.4);
}
.telemetry-tag.session {
  background: rgba(74, 125, 219, 0.15);
  color: var(--accent);
  border: 1px solid rgba(74, 125, 219, 0.4);
}
.telemetry-detail { color: var(--muted); }
.telemetry-detail b { color: var(--text); }
```

**Step 4: Verify build & lint**

Run: `cd frontend && npm run lint && npm run build`
Expected: 0 errors, build succeeds.

**Step 5: Commit**

```bash
git add frontend/src/components/TelemetryPanel.jsx frontend/src/App.jsx frontend/src/App.css
git commit -m "feat(ui): Display dual-tier telemetry separating run cost from session lifetime"
```

---

### Task 4: Frontend Core Moat Elevation (Controlled Proof Expansion + CSS Flex Fix + Auto-Scroll)

**Files:**
- Modify: `frontend/src/components/ReportView.jsx:10-70`
- Modify: `frontend/src/App.jsx:43-75`
- Modify: `frontend/src/App.css:248-275`

**Step 1: Implement controlled proof expansion in `ReportView.jsx`**

1. Maintain `expandedIds` set at `ReportView` level:
   - On load, initialize with the first claim ID: `new Set(report.sections[0]?.claims[0]?.id ? [report.sections[0].claims[0].id] : [])`.
   - Add button to header: `[Expand all proofs / Collapse all]`.
   - Pass `isOpen={expandedIds.has(claim.id)}` and `onToggle={() => toggleClaim(claim.id)}` to `ClaimRow`.
2. Add guarded in-report cost pill:
   ```jsx
   {hasRunSummary && (
     <span className="badge green" title="Deterministic Token Factory & Tavily cost for this run">
       ⚡ {(report.run_summary.tf_tokens_run || 0).toLocaleString()} tokens · {report.run_summary.tavily_searches_run || 0} searches
     </span>
   )}
   ```

**Step 2: Fix CSS in `App.css`**

1. Change `.claim-row` from `display: flex; align-items: baseline;` to `display: flex; flex-direction: column; align-items: stretch; gap: 4px;`.
2. `.claim-line` handles `display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;`.
3. `.claim-proof` sits cleanly underneath with full width and left ink border.

**Step 3: Auto-scroll in `App.jsx`**

On `e.stage === "done"`:
```javascript
setTimeout(() => document.querySelector('.report')?.scrollIntoView({ behavior: 'smooth' }), 100);
```

**Step 4: Verify build & lint**

Run: `cd frontend && npm run lint && npm run build`
Expected: 0 errors, build succeeds.

**Step 5: Commit**

```bash
git add frontend/src/components/ReportView.jsx frontend/src/App.jsx frontend/src/App.css
git commit -m "feat(ui): Auto-expand verification proof, fix claim layout, and auto-scroll to report"
```

---

### Task 5: Frontend Research Output Showcase: Full Draft Text & 1-Click Markdown Copy

**Files:**
- Modify: `frontend/src/components/ReportView.jsx`
- Modify: `frontend/src/App.css`

**Step 1: Implement Draft Text generation & View Switcher**

1. In `ReportView.jsx`:
   - Add view mode state: `const [viewMode, setViewMode] = useState("report");` // "report" | "draft"
   - Generate compiled markdown draft:
     ```javascript
     function buildMarkdownDraft(report) {
       let md = `# Research Report: ${report.brief}\n\n`;
       if (report.bottom_line) {
         md += `## Bottom Line\n${report.bottom_line}\n\n`;
       }
       for (const sec of report.sections) {
         md += `## ${sec.sub_question}\n\n${sec.narrative}\n\n`;
         if (sec.claims.length > 0) {
           md += `### Verified Claims\n`;
           for (const c of sec.claims) {
             const v = report.claim_verdicts?.[c.id] || "unverified";
             md += `- [${v.toUpperCase()}] ${c.text} (Sources: ${c.citation_urls.join(", ")})\n`;
           }
           md += "\n";
         }
       }
       if (report.sources_cited?.length > 0) {
         md += `## Bibliography (Sources Cited)\n`;
         for (const s of report.sources_cited) {
           md += `- [${s.title || s.url}](${s.url})\n`;
         }
       }
       return md;
     }
     ```
   - Render tab switcher: `[Executive Report] [Full Research Draft (Markdown)]`.
   - When in "draft" view, show markdown text with a **"📋 Copy Draft to Clipboard"** button with a "Copied! ✓" visual toast feedback.

**Step 2: Verify build & lint**

Run: `cd frontend && npm run lint && npm run build`
Expected: 0 errors, build succeeds.

**Step 3: Commit**

```bash
git add frontend/src/components/ReportView.jsx frontend/src/App.css
git commit -m "feat(ui): Add full research draft view mode with 1-click markdown export"
```

---

### Task 6: Frontend Rich Source Cards & Interactive Transparency Pool

**Files:**
- Modify: `frontend/src/components/ReportView.jsx`
- Modify: `frontend/src/App.css`

**Step 1: Implement Rich Source Cards & Transparency Pool**

1. Helper to extract domain:
   ```javascript
   function getDomain(url) {
     try { return new URL(url).hostname; } catch { return url; }
   }
   ```
2. Render `sources_cited` as cards:
   - Page Title
   - Domain badge (e.g. `github.com`, `docs.nvidia.com`)
   - Direct link with external arrow icon
3. Render `sources_unused` as the **"Transparency Pool: Evaluated Web Sources (Uncited)"**:
   - Explanation callout: *"Tavily retrieved these live web sources during grounding, but Vera's drafter & verifier discarded them as redundant, unverified, or irrelevant to keep your report grounded in high-trust evidence."*
   - Collapsible toggle: "Show all N evaluated sources" with initial preview of 5.

**Step 2: Verify build & lint**

Run: `cd frontend && npm run lint && npm run build`
Expected: 0 errors, build succeeds.

**Step 3: Commit**

```bash
git add frontend/src/components/ReportView.jsx frontend/src/App.css
git commit -m "feat(ui): Upgrade cited sources and transparency pool with domain cards and inspection"
```

---

### Task 7: Frontend Interactive Memory Panel (Click to View Past Runs)

**Files:**
- Modify: `frontend/src/components/MemoryPanel.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/App.css`

**Step 1: Implement Run Selection in `MemoryPanel.jsx`**

1. Pass `onSelectRun` prop to `MemoryPanel`.
2. Each run row has a clickable title / "View" button that calls `onSelectRun(r.run_uuid)`.
3. In `App.jsx`, implement `handleSelectRun`:
   - Fetches `getReport(runUuid)`
   - Sets `report` and `restoredRunId`
   - Sets `runSummary(rep.run_summary || null)`
   - Smooth scrolls down to the report.

**Step 2: Verify build & lint**

Run: `cd frontend && npm run lint && npm run build`
Expected: 0 errors, build succeeds.

**Step 3: Commit**

```bash
git add frontend/src/components/MemoryPanel.jsx frontend/src/App.jsx frontend/src/App.css
git commit -m "feat(memory): Allow clicking past runs in memory panel to load their report"
```

---

### Task 8: Full Verification, Spec Compliance & Code Quality Review

**Files:**
- Run backend pytest (202+ tests)
- Run frontend lint and build
- Run Spec Compliance Reviewer subagent
- Run Code Quality Reviewer subagent
- Verify clean git status and branch diff
