/* Generated. Do not edit. Run pnpm contracts. */

export type Id = string;
export type Title = string;
export type Status =
  | "analyzing"
  | "awaiting_review"
  | "confirmed"
  | "human_handling"
  | "dismissed";
export type Severity = number;
export type AssessedSeverity = number | null;
export type DisplaySeverity = number;
export type AnalysisRound = number;
export type UpdatedAt = number;
export type SeedSource = string | null;
export type Items = IncidentItem[];
export type NextCursor = string | null;

export interface IncidentPage {
  items: Items;
  next_cursor: NextCursor;
}
export interface IncidentItem {
  id: Id;
  title: Title;
  status: Status;
  severity: Severity;
  assessed_severity: AssessedSeverity;
  display_severity: DisplaySeverity;
  analysis_round: AnalysisRound;
  updated_at: UpdatedAt;
  seed_source: SeedSource;
}
