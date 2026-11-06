/* Generated. Do not edit. Run pnpm contracts. */

/**
 * L3 검증 run의 출력. L3 내부 출력 계약이고 다른 단계는 읽지 않는다. 결과를 낮추는 규칙(확신도 임계값, 근거 종류)은 L3 코드가 적용한다
 */
export interface HuntVerification {
  /**
   * confirmed: 위협 확인, rejected: 가설 기각, inconclusive: 근거 부족
   */
  result: "confirmed" | "rejected" | "inconclusive";
  /**
   * 확신도
   */
  confidence: number;
  /**
   * 이유. 공격자가 쓴 문장이 들어갈 수 있다
   */
  reason: string;
  /**
   * 근거가 된 Alert·Event ID와 도구 호출 기록 ID. 중복 없음
   *
   * Items: 판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID
   */
  evidence_ids: string[];
  /**
   * 모델이 확인한 엔티티. L3 코드가 근거 레코드의 엔티티와 합친다
   */
  entities: Entity[];
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
