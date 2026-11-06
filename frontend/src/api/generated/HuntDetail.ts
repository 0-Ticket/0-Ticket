/* Generated. Do not edit. Run pnpm contracts. */

export type Id = string;
/**
 * 같은 가설 생성 실행에서 나온 Hunt 묶음. Agent Log의 run_id(에이전트 실행 한 번)와 다른 ID다
 */
export type HuntRunId = string;
/**
 * pending: 검증 대기(재시도 대기 포함), confirmed: 위협 발견(L3 Ticket을 만든다), rejected: 가설 기각, inconclusive: 근거 부족, failed: 검증 run이 재시도 한도까지 실패. 모두 L3가 바꾼다
 */
export type Status =
  "pending" | "confirmed" | "rejected" | "inconclusive" | "failed";
/**
 * 가설 문장. 밖에서 온 문자열(뉴스 등)에서 나온 LLM 출력이라 공격자가 쓴 문장이 들어갈 수 있다
 */
export type Hypothesis = string;
export type AttackTechnique = string;
/**
 * ATT&CK 기법 ID(T1190, T1059.004). 중복 없음, 빈 목록 가능
 */
export type AttackTechniques = AttackTechnique[];
/**
 * 검증 결과 확신도. confirmed, rejected, inconclusive일 때만 값이 있다
 */
export type Confidence = number;
/**
 * 검증 결과 이유. confirmed, rejected, inconclusive일 때만 값이 있다. 공격자가 쓴 문장이 들어갈 수 있다
 */
export type Reason = string | null;
/**
 * 판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID
 */
export type EvidenceId = string;
/**
 * 검증 근거가 된 Alert·Event ID와 도구 호출 기록 ID. confirmed는 Alert·Event ID가 1개 이상, rejected는 1개 이상. 중복 없음
 */
export type EvidenceIds = EvidenceId[];
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
 * 검증에서 확인한 엔티티
 */
export type Entities = Entity[];
/**
 * 검증 run 시도 횟수. pending이 아니면 1 이상
 */
export type Attempts = number;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type EpochMs = number;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type CreatedAt = number;
/**
 * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
 */
export type UpdatedAt = number;
export type Id1 = string;
export type Name = string | null;
export type Techniques = Technique[];
export type TicketId = string | null;
export type RunId = string;
export type Task = string | null;
export type Attempt = number | null;
export type Outcome = "ok" | "error";
export type Failure = string | null;
export type TokensIn = number | null;
export type TokensOut = number | null;
export type StartedAt = number;
export type DurationMs = number;
export type Runs = RunSummary[];

export interface HuntDetail {
  hunt: Hunt;
  techniques: Techniques;
  ticket_id: TicketId;
  runs: Runs;
}
export interface Hunt {
  id: Id;
  hunt_run_id: HuntRunId;
  status: Status;
  hypothesis: Hypothesis;
  attack_techniques: AttackTechniques;
  /**
   * 검증 결과 확신도. confirmed, rejected, inconclusive일 때만 값이 있다
   */
  confidence: Confidence | null;
  reason: Reason;
  evidence_ids: EvidenceIds;
  entities: Entities;
  attempts: Attempts;
  /**
   * 검증 결과가 정해진 시각. confirmed, rejected, inconclusive일 때만 값이 있다
   */
  verified_at: EpochMs | null;
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
 * 가설 출처(뉴스·Case 참조) 등 L3 내부 값. 다른 단계는 읽지 않는다
 */
export interface Details {
  [k: string]: unknown;
}
export interface Technique {
  id: Id1;
  name: Name;
}
/**
 * Agent Log를 run_id로 묶은 요약. input·output 원문은 넣지 않는다.
 */
export interface RunSummary {
  run_id: RunId;
  task: Task;
  attempt: Attempt;
  outcome: Outcome;
  failure: Failure;
  tokens_in: TokensIn;
  tokens_out: TokensOut;
  started_at: StartedAt;
  duration_ms: DurationMs;
}
