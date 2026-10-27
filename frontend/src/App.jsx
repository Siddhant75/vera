import { useState } from "react";
import { getReport, openEventStream, runResearch } from "./api";
import PersonaToggle from "./components/PersonaToggle";
import PipelineView from "./components/PipelineView";
import ReportView from "./components/ReportView";
import TelemetryPanel from "./components/TelemetryPanel";
import "./App.css";

const SAMPLE_BRIEF = "Should our startup adopt Kubernetes or serverless for our new ML inference API?";

export default function App() {
  const [persona, setPersona] = useState("engineer");
  const [brief, setBrief] = useState(SAMPLE_BRIEF);
  const [topic, setTopic] = useState("");
  const [events, setEvents] = useState([]);
  const [report, setReport] = useState(null);
  const [running, setRunning] = useState(false);

  const launch = async (delta) => {
    setEvents([]);
    setReport(null);
    setRunning(true);
    try {
      const runId = await runResearch({ brief, topic, persona, delta });
      openEventStream(runId, (e) => {
        setEvents((prev) => [...prev, e]);
        if (e.stage === "done") {
          setReport(e.payload.report);
          setRunning(false);
        } else if (e.stage === "error") {
          setRunning(false);
        }
      });
    } catch {
      setRunning(false);
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
      </div>

      {events.length > 0 && <PipelineView events={events} />}
      <ReportView runId={report ? events.find((e) => e.run_id)?.run_id : null} report={report} />

      <footer>
        <small>
          NVIDIA Nemotron + open models on Nebius Token Factory · live web grounding via Tavily ·
          every claim adversarially verified
        </small>
      </footer>
    </main>
  );
}
