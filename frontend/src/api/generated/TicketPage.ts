/* Generated. Do not edit. Run pnpm contracts. */

export type Id = string;
export type Origin = "auto" | "scenario" | "l1" | "l3";
export type Status = "new" | "closed" | "held" | "escalated" | "linked";
export type Severity = number;
export type CreatedAt = number;
export type UpdatedAt = number;
export type SeedSource = string | null;
export type Items = TicketItem[];
export type NextCursor = string | null;

export interface TicketPage {
  items: Items;
  next_cursor: NextCursor;
}
export interface TicketItem {
  id: Id;
  origin: Origin;
  status: Status;
  severity: Severity;
  created_at: CreatedAt;
  updated_at: UpdatedAt;
  seed_source: SeedSource;
}
