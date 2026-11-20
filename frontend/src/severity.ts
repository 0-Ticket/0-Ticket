// Severity (OCSF severity_id 0-6) shown on screen. Every severity text comes from here.
const names = ["미상", "정보", "낮음", "보통", "높음", "심각", "치명"];

export function severityLabel(value: number | null): string {
  if (value === null) return "—";
  return names[value] ?? names[0];
}
