export function FilterChips({
  label,
  name,
  options,
  value,
  onChange,
}: {
  label: string;
  name: string;
  options: [string, string][];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="filter-chips" role="group" aria-label={name}>
      <span className="filter-label">{label}</span>
      {options.map(([key, text]) => (
        <button
          key={key}
          aria-pressed={value === key}
          onClick={() => onChange(value === key ? "" : key)}
        >
          {value === key && <span aria-hidden="true">× </span>}
          {text}
        </button>
      ))}
    </div>
  );
}
