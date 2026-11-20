// Severity (OCSF severity_id 0-6) shown on screen. Every severity text comes from here.
const names = [
  "미상",
  "1 Level",
  "2 Level",
  "3 Level",
  "4 Level",
  "5 Level",
  "6 Level",
];

export function severityLabel(value: number | null): string {
  if (value === null) return "—";
  return names[value] ?? names[0];
}
