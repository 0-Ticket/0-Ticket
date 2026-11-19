/* Generated. Do not edit. Run pnpm contracts. */

/**
 * L1 1차 판정 상태
 */
export type Triage = Triage1;

/**
 * OCSF 1.9.0 Detection Finding(class_uid 2004) 문서. 해석할 수 없는 원본의 폴백 Alert만 Base Event(0)다. class_uid가 2004이면 finding_info(OCSF 탐지 정보)가 필수다. 우리 쪽 값은 모두 details에 있다. 최상위 time은 OCSF 생성 시각이고 severity_id가 심각도다(DB 컬럼 time·severity와 의미가 다르다)
 */
export interface Alert {
  /**
   * 2004 Detection Finding. 해석할 수 없는 원본의 폴백 Alert만 0(Base Event)
   */
  class_uid: 2004 | 0;
  /**
   * OCSF 생성 시각(epoch 밀리초)
   */
  time: number;
  /**
   * OCSF 심각도. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal, 99 Other
   */
  severity_id: 0 | 1 | 2 | 3 | 4 | 5 | 6 | 99;
  /**
   * 우리 쪽 값. OCSF 속성 이름과 같은 키를 두지 않는다. 아래 6개는 필수이고 그 밖의 값(fallback 등)은 더 올 수 있다
   */
  details: {
    id: string;
    raw_id: string;
    /**
     * 알럿을 만든 SIEM 탐지 룰 ID. 없으면 null(폴백은 항상 null)
     */
    rule_id: string | null;
    entities: Entity[];
    assets: Asset[];
    /**
     * 시나리오 모드에서 일치하지 않은 알럿의 L1 1차 판정. 그 밖에는 null
     */
    triage: Triage | null;
    [k: string]: unknown;
  };
  [k: string]: unknown;
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
