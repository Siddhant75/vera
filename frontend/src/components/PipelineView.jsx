const STAGES = [
  ["planning", "Planning", "Breaking your brief into sub-questions tuned to your persona"],
  ["searching", "Searching", "Live Tavily web search per sub-question"],
  ["drafting", "Drafting", "Atomic claims extracted, every one cited to a fetched source"],
  ["verifying", "Verifying", "Each claim cross-examined by 2+ independent models"],
  ["synthesizing", "Synthesizing", "Persona-voiced report with confidence labels"],
];

export default function PipelineView({ events }) {
  const byStage = {};
  for (const e of events) byStage[e.stage] = e.payload;
  const seen = STAGES.map(([key]) => key).indexOf(events.length ? events[events.length - 1].stage : -1);

  return (
    <div className="pipeline">
      {STAGES.map(([key, title, desc], i) => {
        const payload = byStage[key];
        const state = payload ? (i < seen || key === "done" ? "done" : "active") : "idle";
        return (
          <div key={key} className={`stage ${state}`}>
            <div className="stage-head">
              <span className="stage-num">{i + 1}</span>
              <strong>{title}</strong>
              {state === "active" && <span className="spinner" aria-label="running" />}
            </div>
            <div className="stage-desc">{desc}</div>
            {key === "planning" && payload?.brief && (
              <div className="stage-detail">Brief: {payload.brief}</div>
            )}
            {key === "searching" && payload?.sub_questions && (
              <ul className="stage-detail">
                {payload.sub_questions.map((q, j) => <li key={j}>{q}</li>)}
              </ul>
            )}
            {key === "drafting" && payload && (
              <div className="stage-detail">{payload.source_count} sources grounded</div>
            )}
            {key === "verifying" && payload && (
              <div className="stage-detail">{payload.claim_count} claims under cross-examination</div>
            )}
          </div>
        );
      })}
      {byStage.error && (
        <div className="stage error">
          <strong>Pipeline error</strong>
          <div className="stage-detail">
            {byStage.error.failed_stage}: {byStage.error.detail}
          </div>
        </div>
      )}
    </div>
  );
}
