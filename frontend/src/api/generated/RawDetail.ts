/* Generated. Do not edit. Run pnpm contracts. */

export type Id = string;
export type Kind = "alert" | "event";
/**
 * 가져온 SIEM 연결 프로필 이름
 */
export type SiemProfile = string;
/**
 * SIEM 안에서 문서 하나를 가리키는 값. ELK는 <_index>/<_id>
 */
export type SiemRef = string;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type FetchedAt = number;
/**
 * SIEM이 준 JSON 그대로, json.dumps(ensure_ascii=True) 글자. 되살릴 때는 json.loads를 쓴다(D-049)
 */
export type OriginalText = string;
export type Record = Alert | Event | null;
export type Id1 = string;
export type RawId = string;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type Time = number;
/**
 * OCSF severity_id. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal
 */
export type Severity = number;
/**
 * 한 줄 요약(룰 이름 등)
 */
export type Title = string;
/**
 * 알럿을 만든 SIEM 탐지 룰 ID. 없으면 null
 */
export type RuleId = string | null;
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
export type Entities = Entity[];
/**
 * 엔티티 종류
 */
export type Type1 =
  "ip" | "host" | "user" | "domain" | "url" | "file_hash" | "process";
/**
 * 엔티티 값
 */
export type Value1 = string;
/**
 * 자산 이름
 */
export type Name = string | null;
/**
 * 중요도 1~5. 5가 가장 중요
 */
export type Criticality = number;
/**
 * 담당 부서·사람
 */
export type Owner = string | null;
export type Assets = Asset[];
/**
 * pending: 1차 판정 대기, promoted: Ticket으로 승격, held: 보류(Ticket 없음)
 */
export type Status = "pending" | "promoted" | "held";
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
export type ClassUid = 2004;
export type Id2 = string;
export type RawId1 = string;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type Time1 = number;
/**
 * OCSF class_uid. ocsf.class_uid와 같아야 한다(validate_contract 추가 검사)
 */
export type OcsfClass = number;
/**
 * 한 줄 요약
 */
export type Summary = string;
export type Entities1 = Entity[];
export type Assets1 = Asset[];
export type ClassUid1 = number;
export type NormalizeStatus = "pending" | "succeeded" | "failed";
export type ErrorCode = string | null;
export type SeedSource = string | null;

export interface RawDetail {
  raw_record: RawRecord;
  record: Record;
  normalize_status: NormalizeStatus;
  error_code: ErrorCode;
  seed_source: SeedSource;
}
export interface RawRecord {
  id: Id;
  kind: Kind;
  siem_profile: SiemProfile;
  siem_ref: SiemRef;
  fetched_at: FetchedAt;
  original_text: OriginalText;
}
export interface Alert {
  id: Id1;
  raw_id: RawId;
  time: Time;
  severity: Severity;
  title: Title;
  rule_id: RuleId;
  entities: Entities;
  assets: Assets;
  /**
   * 시나리오 모드에서 일치하지 않은 알럿의 L1 1차 판정. 그 밖에는 null
   */
  triage: Triage | null;
  ocsf: Ocsf;
  details: Details;
}
export interface Entity {
  type: Type;
  value: Value;
  role: Role;
}
export interface Asset {
  entity: Entity1;
  name: Name;
  /**
   * 중요도 1~5. 5가 가장 중요
   */
  criticality: Criticality | null;
  owner: Owner;
}
/**
 * 어느 엔티티의 자산 정보인지. 조회에 쓴 정규화 키(Entity.type, 정규화한 Entity.value)
 */
export interface Entity1 {
  type: Type1;
  value: Value1;
}
export interface Triage {
  status: Status;
  verdict: Verdict | null;
}
export interface Verdict {
  decision: Decision;
  confidence: Confidence;
  reason: Reason;
  evidence_ids: EvidenceIds;
  decided_at: DecidedAt;
}
/**
 * OCSF Detection Finding 전체
 */
export interface Ocsf {
  class_uid: ClassUid;
  [k: string]: unknown;
}
/**
 * 계약에 없는 값. 다른 단계는 읽지 않는다
 */
export interface Details {
  [k: string]: unknown;
}
export interface Event {
  id: Id2;
  raw_id: RawId1;
  time: Time1;
  ocsf_class: OcsfClass;
  summary: Summary;
  entities: Entities1;
  assets: Assets1;
  ocsf: Ocsf1;
  details: Details1;
}
/**
 * 매핑한 OCSF 클래스 전체
 */
export interface Ocsf1 {
  class_uid: ClassUid1;
  [k: string]: unknown;
}
/**
 * 계약에 없는 값. 다른 단계는 읽지 않는다
 */
export interface Details1 {
  [k: string]: unknown;
}
