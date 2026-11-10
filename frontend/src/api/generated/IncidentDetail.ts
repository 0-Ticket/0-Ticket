/* Generated. Do not edit. Run pnpm contracts. */

export type Id = string;
/**
 * L2가 정한 제목
 */
export type Title = string;
/**
 * 분석 요약. L2가 채운다. 분석 전 null
 */
export type Summary = string | null;
/**
 * analyzing: L2 분석 필요·중, held: L2 연속 실패 소진 후 쿨다운 대기, awaiting_review: 사람 검토 대기, confirmed: 사람 승인(Case 생성), human_handling: 사람이 직접 처리, dismissed: 위협 아님으로 종결(L2가 분석 후, 또는 사람이 검토 중이나 직접 처리를 끝낼 때)
 */
export type Status =
  | "analyzing"
  | "awaiting_review"
  | "confirmed"
  | "human_handling"
  | "dismissed"
  | "held";
/**
 * 1개 이상. 중복 없음
 *
 * @minItems 1
 */
export type TicketIds = [TicketId, ...TicketId[]];
export type TicketId = string;
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
 * 소속 Ticket 엔티티와 L2 조사에서 근거와 함께 확인한 엔티티를 모은 것
 */
export type Entities = Entity[];
/**
 * 소속 Alert 심각도 중 최대. 소속 Alert가 없으면 0
 */
export type Severity = number;
/**
 * OCSF severity_id. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal
 */
export type Severity1 = number;
/**
 * L2 분석 시도 순번. 성공·실패마다 증가하고 취소에는 증가하지 않는다
 */
export type AnalysisRound = number;
/**
 * 사람 검토 횟수
 */
export type ReviewRound = number;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type CreatedAt = number;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type UpdatedAt = number;
export type Id1 = string;
export type IncidentId = string;
export type AnalysisRound1 = number;
export type Verdict = "not_threat" | "attempted" | "succeeded" | "inconclusive";
export type Summary1 = string;
/**
 * OCSF severity_id. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal
 */
export type AssessedSeverity = number;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type Time = number;
export type Summary2 = string;
/**
 * @minItems 1
 */
export type EvidenceIds = [EvidenceId, ...EvidenceId[]];
/**
 * 판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID
 */
export type EvidenceId = string;
export type Timeline = TimelineItem[];
export type Id2 = string;
export type Name = string;
/**
 * @minItems 1
 */
export type EvidenceIds1 = [EvidenceId, ...EvidenceId[]];
export type Techniques = Technique[];
export type Impact = string;
export type Cause = string;
export type FurtherRisk = string;
export type EvidenceIds2 = EvidenceId[];
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type CreatedAt1 = number;
export type Artifacts = IncidentArtifact[];
export type Id3 = string;
export type ArtifactId = string;
export type Kind = "detection_rule" | "response_action";
export type Seq = number;
export type Body = string;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type CreatedAt2 = number;
export type Proposals = IncidentProposal[];
export type SeedSource = string | null;

export interface IncidentDetail {
  incident: Incident;
  artifacts: Artifacts;
  proposals: Proposals;
  seed_source: SeedSource;
}
export interface Incident {
  id: Id;
  title: Title;
  summary: Summary;
  status: Status;
  ticket_ids: TicketIds;
  entities: Entities;
  severity: Severity;
  /**
   * L2 분석이 판단한 심각도. 분석 전 null
   */
  assessed_severity: Severity1 | null;
  analysis_round: AnalysisRound;
  review_round: ReviewRound;
  created_at: CreatedAt;
  updated_at: UpdatedAt;
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
export interface IncidentArtifact {
  id: Id1;
  incident_id: IncidentId;
  analysis_round: AnalysisRound1;
  verdict: Verdict;
  summary: Summary1;
  assessed_severity: AssessedSeverity;
  timeline: Timeline;
  techniques: Techniques;
  impact: Impact;
  cause: Cause;
  further_risk: FurtherRisk;
  evidence_ids: EvidenceIds2;
  created_at: CreatedAt1;
}
export interface TimelineItem {
  time: Time;
  summary: Summary2;
  evidence_ids: EvidenceIds;
}
export interface Technique {
  id: Id2;
  name: Name;
  evidence_ids: EvidenceIds1;
}
export interface IncidentProposal {
  id: Id3;
  artifact_id: ArtifactId;
  kind: Kind;
  seq: Seq;
  body: Body;
  created_at: CreatedAt2;
}
