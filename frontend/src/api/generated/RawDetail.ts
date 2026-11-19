/* Generated. Do not edit. Run pnpm contracts. */

export type Id = string;
export type Kind = "alert" | "event";
/**
 * 가져온 SIEM 연결 프로필 이름
 */
export type SiemProfile = string;
/**
 * SIEM 안에서 문서 하나를 가리키는 이스케이프된 저장 키(siem_ref_key 형태). 원래 형태 "<_index>/<_id>"가 아니다. <_index>/<_id>를 JSON 문자열 이스케이프(ensure_ascii)하고 양쪽 따옴표를 뺀 값이다(D-049, soc.ids.siem_ref_key)
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
/**
 * 2004 Detection Finding. 해석할 수 없는 원본의 폴백 Alert만 0(Base Event)
 */
export type ClassUid = 2004 | 0;
/**
 * OCSF 생성 시각(epoch 밀리초)
 */
export type Time = number;
/**
 * OCSF 심각도. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal, 99 Other
 */
export type SeverityId = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 99;
export type Id1 = string;
export type RawId = string;
/**
 * 알럿을 만든 SIEM 탐지 룰 ID. 없으면 null(폴백은 항상 null)
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
/**
 * OCSF 클래스. 0 Base Event, 2003 Compliance Finding, 3002 Authentication, 4001 Network Activity, 4002 HTTP Activity, 4003 DNS Activity, 6003 API Activity
 */
export type ClassUid1 = 0 | 2003 | 3002 | 4001 | 4002 | 4003 | 6003;
/**
 * 활동 발생 시각(epoch 밀리초)
 */
export type Time1 = number;
/**
 * OCSF 심각도. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal, 99 Other
 */
export type SeverityId1 = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 99;
/**
 * 한 줄 요약. DB 컬럼 summary가 여기서 파생된다
 */
export type Message = string | null;
export type Id2 = string;
export type RawId1 = string;
export type Entities1 = Entity[];
export type Assets1 = Asset[];
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
  class_uid: ClassUid;
  time: Time;
  severity_id: SeverityId;
  details: Details;
  [k: string]: unknown;
}
/**
 * 우리 쪽 값. OCSF 속성 이름과 같은 키를 두지 않는다. 아래 6개는 필수이고 그 밖의 값(fallback 등)은 더 올 수 있다
 */
export interface Details {
  id: Id1;
  raw_id: RawId;
  rule_id: RuleId;
  entities: Entities;
  assets: Assets;
  /**
   * 시나리오 모드에서 일치하지 않은 알럿의 L1 1차 판정. 그 밖에는 null
   */
  triage: Triage | null;
  [k: string]: unknown;
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
export interface Event {
  class_uid: ClassUid1;
  time: Time1;
  severity_id: SeverityId1;
  message?: Message;
  details: Details1;
  [k: string]: unknown;
}
/**
 * 우리 쪽 값. OCSF 속성 이름과 같은 키를 두지 않는다. 아래 4개는 필수이고 그 밖의 값은 더 올 수 있다
 */
export interface Details1 {
  id: Id2;
  raw_id: RawId1;
  entities: Entities1;
  assets: Assets1;
  [k: string]: unknown;
}
