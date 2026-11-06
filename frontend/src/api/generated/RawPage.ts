/* Generated. Do not edit. Run pnpm contracts. */

export type RawId = string;
export type RecordId = string | null;
export type NormalizeStatus = "pending" | "succeeded" | "failed";
export type ErrorCode = string | null;
export type FetchedAt = number;
export type Title = string | null;
export type Severity = number | null;
export type SeedSource = string | null;
export type Items = RawItem[];
export type NextCursor = string | null;

export interface RawPage {
  items: Items;
  next_cursor: NextCursor;
}
export interface RawItem {
  raw_id: RawId;
  record_id: RecordId;
  normalize_status: NormalizeStatus;
  error_code: ErrorCode;
  fetched_at: FetchedAt;
  title: Title;
  severity: Severity;
  seed_source: SeedSource;
}
