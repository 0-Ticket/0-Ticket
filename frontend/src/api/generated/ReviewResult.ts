/* Generated. Do not edit. Run pnpm contracts. */

export type Id = string;
export type Title = string;
export type Status =
  | "analyzing"
  | "awaiting_review"
  | "confirmed"
  | "human_handling"
  | "dismissed"
  | "held";
export type Severity = number;
export type AssessedSeverity = number | null;
export type DisplaySeverity = number;
export type AnalysisRound = number;
export type UpdatedAt = number;
export type SeedSource = string | null;
export type CaseId = string | null;

/**
 * 승인·반려 결과. 승인이면 만든 Case의 id, 반려이면 null(#365, D-076).
 */
export interface ReviewResult {
  incident: IncidentItem;
  case_id: CaseId;
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
