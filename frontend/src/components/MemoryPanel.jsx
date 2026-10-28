import { useEffect, useState } from "react";
import { deleteRun, listMemory, purgeMemory } from "../api";

export default function MemoryPanel() {
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
            <div key={r.run_uuid} className="watch-row">
              <span className="muted">{r.created_at} · {r.persona} · {r.topic_key}</span>
              <span>{r.brief.slice(0, 40)}…</span>
              <button type="button" onClick={async () => { await deleteRun(r.run_uuid); refresh(); }}>✕</button>
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
