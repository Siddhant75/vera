import { useEffect, useState } from "react";
import { deleteRun, listMemory, purgeMemory } from "../api";

export default function MemoryPanel({ onSelectRun }) {
  const [mem, setMem] = useState(null);
  const [confirmPurge, setConfirmPurge] = useState("");

  const refresh = () => listMemory().then(setMem).catch(() => {});
  useEffect(() => { refresh(); }, []);

  if (!mem) return null;
  const runs = mem.runs || [];
  return (
    <div className="memory-box">
      <button type="button" className="secondary" onClick={() => { refresh(); }}>
        🧠 What Vera remembers ({runs.length} runs)
      </button>
      {runs.length > 0 && (
        <div className="memory-list">
          {runs.map((r) => (
            <div key={r.run_uuid} className="watch-row memory-run-row">
              {onSelectRun && (
                <button
                  type="button"
                  className="btn-view-run"
                  onClick={() => onSelectRun(r.run_uuid)}
                  title="View this research report"
                >
                  View ↗
                </button>
              )}
              <span className="muted">{r.created_at} · {r.persona} · {r.topic_key}</span>
              <span
                className="memory-run-brief"
                onClick={() => onSelectRun && onSelectRun(r.run_uuid)}
                title="Click to view report"
              >
                {r.brief.slice(0, 45)}…
              </span>
              {r.source && r.source !== "manual" && (
                <span className={`badge ${r.source === "watch" ? "yellow" : ""}`}>{r.source}</span>
              )}
              <button
                type="button"
                className="btn-delete-run"
                onClick={async () => { await deleteRun(r.run_uuid); refresh(); }}
                title="Delete this run"
              >
                ✕
              </button>
            </div>
          ))}
          <div className="purge-row">
            <input value={confirmPurge} onChange={(e) => setConfirmPurge(e.target.value)}
                   placeholder="type DELETE to erase everything Vera remembers" />
            <button type="button" className="danger" disabled={confirmPurge !== "DELETE"}
                    onClick={async () => { await purgeMemory(); setConfirmPurge(""); refresh(); }}>
              Purge all
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
