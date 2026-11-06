/* Generated. Do not edit. Run pnpm contracts. */

export type Succeeded = number;
export type Failed = number;
export type Pending = number;
export type SuccessRatio = number | null;
export type Total = number;
export type Promoted = number;
export type PromotionRatio = number | null;
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
export type AnalyzedIncidents = IncidentItem[];
export type TopIncidents = IncidentItem[];

export interface Dashboard {
  flow: Flow;
  ticket_status: TicketStatus;
  incident_status: IncidentStatus;
  case_status: CaseStatus;
  ticket_severity: TicketSeverity;
  normalization: Normalization;
  hunting: HuntingCounts;
  analyzed_incidents: AnalyzedIncidents;
  top_incidents: TopIncidents;
}
export interface Flow {
  [k: string]: number;
}
export interface TicketStatus {
  [k: string]: number;
}
export interface IncidentStatus {
  [k: string]: number;
}
export interface CaseStatus {
  [k: string]: number;
}
export interface TicketSeverity {
  [k: string]: number;
}
export interface Normalization {
  [k: string]: NormalizeCounts;
}
export interface NormalizeCounts {
  succeeded: Succeeded;
  failed: Failed;
  pending: Pending;
  success_ratio: SuccessRatio;
}
export interface HuntingCounts {
  statuses: Statuses;
  total: Total;
  promoted: Promoted;
  promotion_ratio: PromotionRatio;
}
export interface Statuses {
  [k: string]: number;
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
