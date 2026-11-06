/* Generated. Do not edit. Run pnpm contracts. */

export type Id = string;
/**
 * auto: 기본 모드, scenario: 시나리오 일치, l1: L1 1차 판정으로 승격, l3: L3 헌팅 발견
 */
export type Origin = "auto" | "scenario" | "l1" | "l3";
/**
 * new: L1 판정 대기, closed: 오탐 종결, held: 보류, escalated: L2 대기, linked: Incident에 붙음
 */
export type Status = "new" | "closed" | "held" | "escalated" | "linked";
export type AlertId = string;
/**
 * origin이 auto, scenario, l1이면 Alert 하나만 가리킨다. 중복 없음
 */
export type AlertIds = AlertId[];
export type HuntId = string;
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
 * 소속 Alert 엔티티를 모은 것
 */
export type Entities = Entity[];
export type Decision = "benign" | "malicious" | "undetermined";
export type Confidence = number;
/**
 * 판정 이유
 */
export type Reason = string;
/**
 * 판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID
 */
export type EvidenceId = string;
/**
 * 판정 근거가 된 Alert·Event ID와 도구 호출 기록 ID. decision이 benign·malicious이면 1개 이상. 중복 없음
 */
export type EvidenceIds = EvidenceId[];
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type DecidedAt = number;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type CreatedAt = number;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type UpdatedAt = number;
export type Severity = number;
export type SeedSource = string | null;

export interface TicketDetail {
  ticket: Ticket;
  severity: Severity;
  seed_source: SeedSource;
}
export interface Ticket {
  id: Id;
  origin: Origin;
  status: Status;
  alert_ids: AlertIds;
  /**
   * 이 Ticket을 만든 Hunt. origin이 l3이면 값이 있고, 그 밖에는 null. Hunt 하나에 Ticket 하나
   */
  hunt_id: HuntId | null;
  entities: Entities;
  /**
   * L1 Ticket 판정. status가 new이면 null
   */
  verdict: Verdict | null;
  created_at: CreatedAt;
  updated_at: UpdatedAt;
  details: Details;
}
export interface Entity {
  type: Type;
  value: Value;
  role: Role;
}
export interface Verdict {
  decision: Decision;
  confidence: Confidence;
  reason: Reason;
  evidence_ids: EvidenceIds;
  decided_at: DecidedAt;
}
/**
 * 계약에 없는 값. 다른 단계는 읽지 않는다
 */
export interface Details {
  [k: string]: unknown;
}
