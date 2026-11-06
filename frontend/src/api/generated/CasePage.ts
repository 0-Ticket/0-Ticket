/* Generated. Do not edit. Run pnpm contracts. */

export type Id = string;
export type IncidentId = string;
export type Title = string;
export type Severity = number;
export type Status = "open" | "in_progress" | "resolved";
export type ConfirmedAt = number;
export type SeedSource = string | null;
export type Items = CaseItem[];
export type NextCursor = string | null;

export interface CasePage {
  items: Items;
  next_cursor: NextCursor;
}
export interface CaseItem {
  id: Id;
  incident_id: IncidentId;
  title: Title;
  severity: Severity;
  status: Status;
  confirmed_at: ConfirmedAt;
  seed_source: SeedSource;
}
