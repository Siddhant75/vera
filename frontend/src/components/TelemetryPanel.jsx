import { useEffect, useState } from "react";
import { getTelemetry } from "../api";

export default function TelemetryPanel() {
  const [snap, setSnap] = useState(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const t = await getTelemetry();
        if (alive) setSnap(t);
      } catch { /* backend not up yet */ }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  if (!snap) return null;
  return (
    <div className="telemetry">
      <span className="pill live">● Live</span>
      <span className="pill">Token Factory: {snap.tf_calls} calls / {snap.tf_tokens} tokens</span>
      <span className="pill">
        Tavily: {snap.tavily_grounding} grounding · {snap.tavily_prosecution} prosecution ·{" "}
        {snap.tavily_recheck} re-check
      </span>
      <span className="pill">verified: {snap.claims_verified} claims</span>
    </div>
  );
}
