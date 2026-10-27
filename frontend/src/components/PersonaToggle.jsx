import { useEffect, useState } from "react";
import { getProfile, saveProfile } from "../api";

export default function PersonaToggle({ persona, onChange }) {
  const [open, setOpen] = useState(false);
  const [profile, setProfile] = useState(null);

  useEffect(() => {
    getProfile().then((p) => setProfile(p)).catch(() => {});
  }, []);

  const set = (field) => (e) => setProfile({ ...profile, [field]: e.target.value });

  const save = async () => {
    await saveProfile(profile);
    onChange(profile.persona);
    setOpen(false);
  };

  const options = [
    ["engineer", "Engineer"],
    ["founder", "Founder"],
    ["analyst", "Analyst"],
  ];

  return (
    <div>
      <div className="persona-row">
        <div className="persona-toggle" role="group" aria-label="Persona">
          {options.map(([value, label]) => (
            <button
              key={value}
              className={persona === value ? "active" : ""}
              onClick={() => { onChange(value); if (profile) setProfile({ ...profile, persona: value }); }}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
        <button className="secondary" type="button" onClick={() => setOpen(!open)}>
          {open ? "Hide profile" : "Tell Vera about you"}
        </button>
      </div>
      {open && profile && (
        <div className="profile-panel">
          <label>Role / context
            <input value={profile.role_context || ""} onChange={set("role_context")}
                   placeholder="CTO of a 10-person startup" />
          </label>
          <label>Current goals
            <input value={profile.goals || ""} onChange={set("goals")}
                   placeholder="ship ML inference API cheaply" />
          </label>
          <label>Expertise notes
            <input value={profile.expertise_notes || ""} onChange={set("expertise_notes")}
                   placeholder="knows Docker, new to Kubernetes" />
          </label>
          <label>Excluded sources (comma-separated domains)
            <input value={(profile.excluded_sources || []).join(", ")} onChange={(e) =>
              setProfile({ ...profile, excluded_sources: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                   placeholder="medium.com, pinterest.com" />
          </label>
          <button type="button" onClick={save}>Save profile</button>
        </div>
      )}
    </div>
  );
}
