/* Generated. Do not edit. Run pnpm contracts. */

export type Id = string;
export type HuntRunId = string;
export type Status =
  "pending" | "confirmed" | "rejected" | "inconclusive" | "failed";
export type Hypothesis = string;
export type AttackTechniques = string[];
export type Confidence = number | null;
export type Attempts = number;
export type VerifiedAt = number | null;
export type CreatedAt = number;
export type UpdatedAt = number;
export type Items = HuntListItem[];
export type NextCursor = string | null;

export interface HuntPage {
  items: Items;
  next_cursor: NextCursor;
}
export interface HuntListItem {
  id: Id;
  hunt_run_id: HuntRunId;
  status: Status;
  hypothesis: Hypothesis;
  attack_techniques: AttackTechniques;
  confidence: Confidence;
  attempts: Attempts;
  verified_at: VerifiedAt;
  created_at: CreatedAt;
  updated_at: UpdatedAt;
}
