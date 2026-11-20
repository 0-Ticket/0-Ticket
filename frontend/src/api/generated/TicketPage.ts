/* Generated. Do not edit. Run pnpm contracts. */

export type Id = string;
export type Title = string;
export type Origin = "auto" | "scenario" | "l1" | "l3";
export type Status = "new" | "closed" | "held" | "escalated" | "linked";
export type Severity = number;
export type CreatedAt = number;
export type UpdatedAt = number;
export type SeedSource = string | null;
export type Id1 = string;
export type Title1 = string;
export type Status1 =
  | "analyzing"
  | "awaiting_review"
  | "confirmed"
  | "human_handling"
  | "dismissed"
  | "held";
export type Severity1 = number;
export type AssessedSeverity = number | null;
export type DisplaySeverity = number;
export type Items = TicketItem[];
export type NextCursor = string | null;

export interface TicketPage {
  items: Items;
  next_cursor: NextCursor;
}
export interface TicketItem {
  id: Id;
  title: Title;
  origin: Origin;
  status: Status;
  severity: Severity;
  created_at: CreatedAt;
  updated_at: UpdatedAt;
  seed_source: SeedSource;
  incident: TicketIncident | null;
}
/**
 * Ticket이 붙은 Incident 요약. 필드 이름과 계산은 IncidentItem과 같다(#345).
 */
export interface TicketIncident {
  id: Id1;
  title: Title1;
  status: Status1;
  severity: Severity1;
  assessed_severity: AssessedSeverity;
  display_severity: DisplaySeverity;
}
