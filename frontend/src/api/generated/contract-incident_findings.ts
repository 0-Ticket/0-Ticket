/* Generated. Do not edit. Run pnpm contracts. */

/**
 * L2 Incident 조사 run의 출력. 사실과 그 근거만 담는다
 */
export interface IncidentFindings {
  timeline: {
    /**
     * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
     */
    time: number;
    summary: string;
    /**
     * @minItems 1
     *
     * Items: 판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID
     */
    evidence_ids: [string, ...string[]];
  }[];
  entities: {
    entity: Entity;
    /**
     * @minItems 1
     *
     * Items: 판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID
     */
    evidence_ids: [string, ...string[]];
  }[];
  /**
   * 어느 항목에도 붙지 않은 근거. 비어도 된다
   *
   * Items: 판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID
   */
  evidence_ids: string[];
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
