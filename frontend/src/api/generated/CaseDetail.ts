/* Generated. Do not edit. Run pnpm contracts. */

export type Id = string;
export type IncidentId = string;
/**
 * 승인 시점 Incident 제목
 */
export type Title = string;
/**
 * 승인 시점 Incident summary를 그대로 복사
 */
export type Summary = string | null;
/**
 * 승인 시점 assessed_severity, 없으면 severity
 */
export type Severity = number;
/**
 * 엔티티 종류
 */
export type Type =
  "ip" | "host" | "user" | "domain" | "url" | "file_hash" | "process";
/**
 * 엔티티 값
 */
export type Value = string;
/**
 * 역할. 모르면 null
 */
export type Role = ("src" | "dst" | "actor" | "target") | null;
/**
 * 승인 시점 엔티티
 */
export type Entities = Entity[];
/**
 * 승인한 사람
 */
export type ConfirmedBy = string;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type ConfirmedAt = number;
/**
 * open → in_progress → resolved. 사람이 화면에서 바꾼다
 */
export type Status = "open" | "in_progress" | "resolved";
/**
 * 담당 분석가
 */
export type Assignee = string | null;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type EpochMs = number;
export type SeedSource = string | null;

export interface CaseDetail {
  case: Case;
  seed_source: SeedSource;
}
export interface Case {
  id: Id;
  incident_id: IncidentId;
  title: Title;
  summary: Summary;
  severity: Severity;
  entities: Entities;
  confirmed_by: ConfirmedBy;
  confirmed_at: ConfirmedAt;
  status: Status;
  assignee: Assignee;
  /**
   * status가 resolved이면 필수, 그 밖에는 null
   */
  resolved_at: EpochMs | null;
  details: Details;
}
export interface Entity {
  type: Type;
  value: Value;
  role: Role;
}
/**
 * 계약에 없는 값. 다른 단계는 읽지 않는다
 */
export interface Details {
  [k: string]: unknown;
}
