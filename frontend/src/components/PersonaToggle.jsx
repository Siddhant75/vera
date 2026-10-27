export default function PersonaToggle({ persona, onChange }) {
  const options = [
    ["engineer", "Engineer"],
    ["founder", "Founder"],
    ["analyst", "Analyst"],
  ];
  return (
    <div className="persona-toggle" role="group" aria-label="Persona">
      {options.map(([value, label]) => (
        <button
          key={value}
          className={persona === value ? "active" : ""}
          onClick={() => onChange(value)}
          type="button"
        >
          {label}
        </button>
      ))}
    </div>
  );
}
