import { useEffect, useState } from "react";
import { addWatch, listWatches, removeWatch } from "../api";

const STATUS_COLOR = {
  changed: "var(--green)",
  "no-change": "var(--muted)",
  error: "var(--red)",
  "budget-limited": "var(--yellow)",
};

export default function WatchToggle({ topic, brief, persona }) {
  const [watches, setWatches] = useState([]);
  const [open, setOpen] = useState(false);

  const refresh = () => listWatches().then(setWatches).catch(() => {});
  useEffect(() => { refresh(); }, []);

  const watch = async () => {
    await addWatch(topic || brief.slice(0, 40), brief, persona);
    refresh();
  };

  return (
    <div className="watch-box">
      <button type="button" className="secondary" onClick={() => setOpen(!open)}>
        {open ? "Hide watches" : "⏱ Watch topics"} ({watches.length})
      </button>
      {open && (
        <div className="watch-list">
          {watches.length === 0 && <small className="muted">No watched topics yet. Watch one and Vera re-researchs it automatically.</small>}
          {watches.map((w) => (
            <div key={w.id} className="watch-row">
              <strong>{w.topic}</strong>
              <span style={{ color: STATUS_COLOR[w.last_status] || "var(--muted)" }}>
                {w.last_status || "pending first check"}{w.last_changes != null ? ` (${w.last_changes} changes)` : ""}
              </span>
              <span className="muted">every {w.interval_hours}h</span>
              <button type="button" onClick={async () => { await removeWatch(w.id); refresh(); }}>✕</button>
              {w.last_digest && (
                <details className="watch-digest">
                  <summary>last digest</summary>
                  <small>{w.last_digest}</small>
                </details>
              )}
            </div>
          ))}
          {topic && brief && (
            <button type="button" onClick={watch}>Watch "{topic}" every 6h</button>
          )}
        </div>
      )}
    </div>
  );
}
