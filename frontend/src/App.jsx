import { useState } from "react";
import { getLastRunReport, getReport, openEventStream, runResearch, runSkillV2 } from "./api";
import PersonaToggle from "./components/PersonaToggle";
import PipelineView from "./components/PipelineView";
import ReportView from "./components/ReportView";
import TelemetryPanel from "./components/TelemetryPanel";
import WatchToggle from "./components/WatchToggle";
import SkillsPanel from "./components/SkillsPanel";
import NotesPanel from "./components/NotesPanel";
import MemoryPanel from "./components/MemoryPanel";
import "./App.css";

const SAMPLE_BRIEF = "Should our startup adopt Kubernetes or serverless for our new ML inference API?";

export default function App() {
  const [persona, setPersona] = useState("engineer");
  const [brief, setBrief] = useState(SAMPLE_BRIEF);
  const [topic, setTopic] = useState("");
  const [events, setEvents] = useState([]);
  const [report, setReport] = useState(null);
  const [runSummary, setRunSummary] = useState(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState(null);
  const [restoredRunId, setRestoredRunId] = useState(null);

  // restore the last report on load — research survives a page refresh
  useEffect(() => {
    getLastRunReport().then(({ report: rep, runId }) => {
      if (rep && !rep.error && !report) { setReport(rep); setRestoredRunId(runId); }
    }).catch(() => {});
  }, []);

  const runByName = async (skillName, vars = {}, watch = false) => {
    setEvents([]);
    setReport(null);
    setRunSummary(null);
    setRunError(null);
    setRunning(true);
    try {
      const runId = await runSkillV2(skillName, vars, watch);
      openEventStream(runId, (e) => {
        setEvents((prev) => [...prev, e]);
        if (e.stage === "done") {
          setReport(e.payload.report);
          setRunSummary(e.payload.run_summary || null);
          setRunning(false);
        } else if (e.stage === "error") {
          setRunning(false);
        }
      });
    } catch (e) {
      setRunning(false);
      setRunError(e.message || "skill run failed");
    }
  };

  const launch = async (delta) => {
    setEvents([]);
    setReport(null);
    setRunSummary(null);
    setRunError(null);
    setRunning(true);
    try {
      const runId = await runResearch({ brief, topic, persona, delta });
      openEventStream(runId, (e) => {
        setEvents((prev) => [...prev, e]);
        if (e.stage === "done") {
          setReport(e.payload.report);
          setRunSummary(e.payload.run_summary || null);
          setRunning(false);
        } else if (e.stage === "error") {
          setRunning(false);
        }
      });
    } catch (e) {
      setRunning(false);
      setRunError(e.message || "research run failed");
    }
  };

  return (
    <main>
      <header>
        <h1>Vera</h1>
        <p className="tagline">Research that knows you, and proves it.</p>
      </header>

      <TelemetryPanel />

      <div className="controls">
        <PersonaToggle persona={persona} onChange={setPersona} />
        <textarea
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          rows={3}
          placeholder="What should Vera research?"
        />
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="Topic tag (optional — enables delta research on repeat runs)"
        />
        <div className="actions">
          <button disabled={running} onClick={() => launch(false)} type="button">
            {running ? "Researching…" : "Run Research"}
          </button>
          <button disabled={running || !topic} onClick={() => launch(true)} type="button" className="secondary">
            Run Delta (what changed)
          </button>
        </div>
        {runError && <p className="run-error" role="alert">{runError}</p>}
        <WatchToggle topic={topic} brief={brief} persona={persona} />
        <SkillsPanel current={{ persona, brief, topic, excluded_sources: [] }} onRun={runByName} />
        <NotesPanel topic={topic} />
        <MemoryPanel />
      </div>

      {events.length > 0 && <PipelineView events={events} />}
      {runSummary && (
        <div className="run-summary">
          Searches {runSummary.searches_used}/{runSummary.search_budget} · {runSummary.tf_tokens_run} tokens ·{" "}
          {runSummary.claims} claims{runSummary.reused > 0 ? ` · ${runSummary.reused} reused` : ""}
        </div>
      )}
      <ReportView runId={(report ? events.find((e) => e.run_id)?.run_id : null) || restoredRunId} report={report} />

      <footer>
        <small>
          NVIDIA Nemotron + open models on Nebius Token Factory · live web grounding via Tavily ·
          every claim adversarially verified
        </small>
      </footer>
    </main>
  );
}
