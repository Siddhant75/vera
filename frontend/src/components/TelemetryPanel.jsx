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
