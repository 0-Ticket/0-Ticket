import { statusNames } from "./constants";
import { severityLabel } from "./severity";

export function Severity({ value }: { value: number | null }) {
  return value === null ? (
    <span>—</span>
  ) : (
    <span className={`badge severity s${value}`}>{severityLabel(value)}</span>
  );
}
export function Status({ value }: { value: string }) {
  return (
    <span className={`badge status-${value}`}>
      {statusNames[value] ?? value}
    </span>
  );
}
