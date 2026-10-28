import { useEffect, useState } from "react";
import { addNote, deleteNote, listNotes } from "../api";

const NEVER_PASTE = "Never paste: passwords, API keys, account numbers, medical records — anything you wouldn't tell a cloud service. Notes live on your machine but their context is processed by Nebius Token Factory.";

export default function NotesPanel({ topic }) {
  const [notes, setNotes] = useState([]);
  const [text, setText] = useState("");
  const [warnings, setWarnings] = useState([]);
  const [open, setOpen] = useState(false);

  const refresh = () => { if (topic) listNotes(topic).then(setNotes).catch(() => {}); };
  useEffect(() => { refresh(); }, [topic]);

  const save = async () => {
    if (!text.trim() || !topic) return;
    const res = await addNote(topic, text);
    setWarnings(res.warnings || []);
    setText("");
    refresh();
  };

  return (
    <div className="notes-box">
      <button type="button" className="secondary" onClick={() => setOpen(!open)}>
        {open ? "Hide private notes" : "🔒 Private notes"} {topic ? `for "${topic}"` : ""} ({notes.length})
      </button>
      {open && (
        <div className="notes-list">
          <small className="muted">{NEVER_PASTE}</small>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3}
                    placeholder="Private context: internal constraints, team knowledge, your own data…" />
          <button type="button" onClick={save} disabled={!topic}>Add note</button>
          {!topic && <small className="muted">Set a topic tag first — notes attach to topics.</small>}
          {warnings.length > 0 && (
            <div className="warning-box">⚠ This looks like it contains: {warnings.join(", ")}. Don't paste secrets.</div>
          )}
          {notes.map((n) => (
            <div key={n.id} className="watch-row">
              <span className="muted">{n.created_at} — {n.content.slice(0, 60)}…</span>
              <button type="button" onClick={async () => { await deleteNote(n.id); refresh(); }}>✕</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
