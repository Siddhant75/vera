import { useEffect, useState } from "react";
import { deleteSkill, listSkills, saveSkill } from "../api";

export default function SkillsPanel({ current, onRun }) {
  const [skills, setSkills] = useState([]);
  const [name, setName] = useState("");
  const [open, setOpen] = useState(false);

  const refresh = () => listSkills().then(setSkills).catch(() => {});
  useEffect(() => { refresh(); }, []);

  const save = async () => {
    if (!name.trim() || !current.brief) return;
    await saveSkill({
      name: name.trim(),
      persona: current.persona,
      brief_template: current.brief,
      topic: current.topic || "",
      trusted_sources: [],
      excluded_sources: current.excluded_sources || [],
    });
    setName("");
    refresh();
  };

  return (
    <div className="skills-box">
      <button type="button" className="secondary" onClick={() => setOpen(!open)}>
        {open ? "Hide skills" : "⚙ Skills"} ({skills.length})
      </button>
      {open && (
        <div className="skills-list">
          <div className="skill-save">
            <input value={name} onChange={(e) => setName(e.target.value)}
                   placeholder="Save current research as skill… e.g. 'infra-watch'" />
            <button type="button" onClick={save}>Save</button>
          </div>
          {skills.map((s) => (
            <div key={s.name} className="watch-row">
              <strong>{s.name}</strong>
              <span className="muted">{s.persona} · {s.brief_template.slice(0, 40)}…</span>
              <button type="button" onClick={() => onRun(s.name)}>Run</button>
              <button type="button" onClick={async () => { await deleteSkill(s.name); refresh(); }}>✕</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
