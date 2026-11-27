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
  /**
   * 근거로 쓰려고 고른 SIEM 문서의 저장 키(#382). evidence_ids와 별개다(아직 ID가 없다). 이 run의 도구 결과에 보인 것만 쓸 수 있고, 워커가 가져와 저장한 뒤 evt_ ID를 발급하면 보고 단계가 그 ID로 인용한다. 중복 없음
   *
   * Items: SIEM 안에서 문서 하나를 가리키는 이스케이프된 저장 키(siem_ref_key 형태). 원래 형태 "<_index>/<_id>"가 아니다. <_index>/<_id>를 JSON 문자열 이스케이프(ensure_ascii)하고 양쪽 따옴표를 뺀 값이다(D-049, soc.ids.siem_ref_key). 근거 ID가 아니라 발급 전 문서를 가리킨다
   */
  siem_refs: string[];
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
