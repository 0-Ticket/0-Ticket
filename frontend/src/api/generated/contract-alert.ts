/* Generated. Do not edit. Run pnpm contracts. */

/**
 * L1 1차 판정 상태
 */
export type Triage = Triage1;

/**
 * OCSF 1.9.0 Detection Finding(class_uid 2004)으로 정규화한 알럿
 */
export interface Alert {
  id: string;
  raw_id: string;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  time: number;
  /**
   * OCSF severity_id. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal
   */
  severity: number;
  /**
   * 한 줄 요약(룰 이름 등)
   */
  title: string;
  /**
   * 알럿을 만든 SIEM 탐지 룰 ID. 없으면 null
   */
  rule_id: string | null;
  entities: Entity[];
  assets: Asset[];
  /**
   * 시나리오 모드에서 일치하지 않은 알럿의 L1 1차 판정. 그 밖에는 null
   */
  triage: Triage | null;
  /**
   * OCSF Detection Finding 전체
   */
  ocsf: {
    class_uid: 2004;
    [k: string]: unknown;
  };
  /**
   * 계약에 없는 값. 다른 단계는 읽지 않는다
   */
  details: {
    [k: string]: unknown;
  };
}
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
 * Lookup으로 붙인 자산 정보
 */
export interface Asset {
  /**
   * 어느 엔티티의 자산 정보인지. 조회에 쓴 정규화 키(Entity.type, 정규화한 Entity.value)
   */
  entity: {
    /**
     * 엔티티 종류
     */
    type: "ip" | "host" | "user" | "domain" | "url" | "file_hash" | "process";
    /**
     * 엔티티 값
     */
    value: string;
  };
  /**
   * 자산 이름
   */
  name: string | null;
  /**
   * 중요도 1~5. 5가 가장 중요
   */
  criticality: number | null;
  /**
   * 담당 부서·사람
   */
  owner: string | null;
}
export interface Triage1 {
  /**
   * pending: 1차 판정 대기, promoted: Ticket으로 승격, held: 보류(Ticket 없음)
   */
  status: "pending" | "promoted" | "held";
  verdict: Verdict | null;
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
