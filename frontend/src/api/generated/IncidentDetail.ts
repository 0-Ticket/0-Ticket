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
export type Title1 = string;
export type Decision = ("benign" | "malicious" | "undetermined") | null;
export type Severity2 = number;
export type CreatedAt1 = number;
export type EvidenceCount = number;
export type AlertIds = string[];
export type Entities1 = Entity[];
export type Tickets = IncidentTicket[];
export type Id2 = string;
export type Time = number;
export type Entities2 = Entity[];
export type Alerts = IncidentAlert[];
export type Id3 = string;
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
export type Time1 = number;
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
export type Id4 = string;
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
export type CreatedAt2 = number;
export type Artifacts = IncidentArtifact[];
export type Id5 = string;
export type ArtifactId = string;
export type Kind = "response" | "detection";
/**
 * 한 Artifact의 권고 조치 목록 전체의 순서(1부터)
 */
export type Seq = number;
/**
 * 옛 구조에서 옮긴 행(마이그레이션 0202)은 null
 */
export type Priority = ("high" | "medium" | "low") | null;
/**
 * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. 옛 행은 본문 첫 줄을 정리한 값
 */
export type Title2 = string;
/**
 * 구체적인 조치. 탐지 룰이면 룰 내용. 길이 한도는 분석 출력 계약만 지킨다(옛 body가 더 길 수 있다)
 */
export type Detail = string;
/**
 * 이 사건의 어떤 사실 때문에 필요한지. 옛 행은 null
 */
export type Rationale = string | null;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type CreatedAt3 = number;
export type Proposals = IncidentProposal[];
export type TicketId1 = string;
export type Coverage = "complete" | "incomplete" | "legacy" | "unknown";
export type Reason = string | null;
export type IncidentId1 = string;
export type TicketId2 = string;
export type Id6 = string;
export type Kind1 = "ticket" | "alert" | "hunt" | "entity" | "incident";
export type Type1 = string | null;
export type Value1 = string | null;
export type Nodes = GraphNode[];
export type From = string;
export type To = string;
export type Kind2 = string;
export type Edges = GraphEdge[];
export type Paths = GraphPath[];
export type VectorOnly = boolean;
export type CandidateCount = number;
export type VectorScore = number | null;
export type RepresentativeTicketId = string | null;
export type TicketGraphs = IncidentTicketGraph[];
export type Type2 = string;
export type Value2 = string;
export type Criticality = number;
export type EntityCriticality = EntityCriticality1[];
export type SeedSource = string | null;

export interface IncidentDetail {
  incident: Incident;
  tickets: Tickets;
  alerts: Alerts;
  artifacts: Artifacts;
  proposals: Proposals;
  ticket_graphs?: TicketGraphs;
  entity_criticality: EntityCriticality;
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
/**
 * Incident 상세의 소속 Ticket. 제목은 Ticket이 만들어질 때의 값이다(D-070).
 */
export interface IncidentTicket {
  id: Id1;
  title: Title1;
  decision: Decision;
  severity: Severity2;
  created_at: CreatedAt1;
  evidence_count: EvidenceCount;
  alert_ids: AlertIds;
  entities: Entities1;
}
/**
 * Incident의 Alert 요약. 엔티티 표의 연결 수·최초 관측 계산에 쓴다(#379, D-080).
 */
export interface IncidentAlert {
  id: Id2;
  time: Time;
  entities: Entities2;
}
export interface IncidentArtifact {
  id: Id3;
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
  created_at: CreatedAt2;
}
export interface TimelineItem {
  time: Time1;
  summary: Summary2;
  evidence_ids: EvidenceIds;
}
export interface Technique {
  id: Id4;
  name: Name;
  evidence_ids: EvidenceIds1;
}
export interface IncidentProposal {
  id: Id5;
  artifact_id: ArtifactId;
  kind: Kind;
  seq: Seq;
  priority: Priority;
  title: Title2;
  detail: Detail;
  rationale: Rationale;
  created_at: CreatedAt3;
}
export interface IncidentTicketGraph {
  ticket_id: TicketId1;
  coverage: Coverage;
  reason: Reason;
  paths: Paths;
  vector_only?: VectorOnly;
  candidate_count?: CandidateCount;
  vector_score?: VectorScore;
  representative_ticket_id?: RepresentativeTicketId;
}
export interface GraphPath {
  incident_id: IncidentId1;
  ticket_id: TicketId2;
  nodes: Nodes;
  edges: Edges;
}
export interface GraphNode {
  id: Id6;
  kind: Kind1;
  type?: Type1;
  value?: Value1;
}
export interface GraphEdge {
  from: From;
  to: To;
  kind: Kind2;
}
/**
 * Incident의 Alert가 가진 자산 중요도를 엔티티 키별 최댓값으로 모은 것(#376, D-078).
 */
export interface EntityCriticality1 {
  type: Type2;
  value: Value2;
  criticality: Criticality;
}
