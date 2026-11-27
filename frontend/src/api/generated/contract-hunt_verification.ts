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
   * 검증 근거로 쓰려고 고른 SIEM 문서의 저장 키(#382). evidence_ids와 별개다(아직 ID가 없다). 이 run의 도구 결과에 보인 것만 쓸 수 있고, 워커가 가져와 저장한 뒤 evt_ ID를 발급해 evidence_ids에 더한다. 중복 없음
   *
   * Items: SIEM 안에서 문서 하나를 가리키는 이스케이프된 저장 키(siem_ref_key 형태). 원래 형태 "<_index>/<_id>"가 아니다. <_index>/<_id>를 JSON 문자열 이스케이프(ensure_ascii)하고 양쪽 따옴표를 뺀 값이다(D-049, soc.ids.siem_ref_key). 근거 ID가 아니라 발급 전 문서를 가리킨다
   */
  siem_refs: string[];
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
