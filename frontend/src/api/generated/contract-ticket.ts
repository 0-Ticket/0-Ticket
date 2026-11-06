/* Generated. Do not edit. Run pnpm contracts. */

/**
 * L1 Ticket 판정의 단위. 여러 Alert를 묶을 수 있다
 */
export type Ticket = {
  id: string;
  /**
   * auto: 기본 모드, scenario: 시나리오 일치, l1: L1 1차 판정으로 승격, l3: L3 헌팅 발견
   */
  origin: "auto" | "scenario" | "l1" | "l3";
  /**
   * new: L1 판정 대기, closed: 오탐 종결, held: 보류, escalated: L2 대기, linked: Incident에 붙음
   */
  status: "new" | "closed" | "held" | "escalated" | "linked";
  /**
   * origin이 auto, scenario, l1이면 Alert 하나만 가리킨다. 중복 없음
   */
  alert_ids: string[];
  /**
   * 이 Ticket을 만든 Hunt. origin이 l3이면 값이 있고, 그 밖에는 null. Hunt 하나에 Ticket 하나
   */
  hunt_id: string | null;
  /**
   * 소속 Alert 엔티티를 모은 것
   */
  entities: Entity[];
  /**
   * L1 Ticket 판정. status가 new이면 null
   */
  verdict: Verdict | null;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  created_at: number;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  updated_at: number;
  /**
   * 계약에 없는 값. 다른 단계는 읽지 않는다
   */
  details: {
    [k: string]: unknown;
  };
};

/**
 * 알럿·이벤트·Ticket·Incident에 나온 엔티티 하나
 */
export interface Entity {
  /**
   * 엔티티 종류
   */
  type: "ip" | "host" | "user" | "domain" | "url" | "file_hash" | "process";
  /**
   * 엔티티 값
   */
  value: string;
  /**
   * 역할. 모르면 null
   */
  role: ("src" | "dst" | "actor" | "target") | null;
}
/**
 * L1 판정. Alert의 1차 판정과 Ticket 판정이 같은 모양을 쓴다
 */
export interface Verdict {
  decision: "benign" | "malicious" | "undetermined";
  confidence: number;
  /**
   * 판정 이유
   */
  reason: string;
  /**
   * 판정 근거가 된 Alert·Event ID와 도구 호출 기록 ID. decision이 benign·malicious이면 1개 이상. 중복 없음
   *
   * Items: 판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID
   */
  evidence_ids: string[];
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  decided_at: number;
}
