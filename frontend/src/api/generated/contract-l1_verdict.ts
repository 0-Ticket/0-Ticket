/* Generated. Do not edit. Run pnpm contracts. */

/**
 * L1 판정 모델의 출력(#382). 저장하는 Verdict(common/verdict.schema.json)에 siem_refs를 더한 모양이다. siem_refs는 아직 발급되지 않은 SIEM 문서를 가리켜 저장하지 않는다. 워커가 그 문서를 가져와 evt_ ID를 발급하면 근거는 evidence_ids로 들어간다.
 */
export interface L1Verdict {
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
   * 근거로 쓰려고 고른 SIEM 문서의 저장 키. evidence_ids와 별개다(아직 ID가 없다). 이 run의 도구 결과에 보인 것만 쓸 수 있고, 워커가 가져와 저장한 뒤 evt_ ID를 발급한다. 중복 없음
   *
   * Items: SIEM 안에서 문서 하나를 가리키는 이스케이프된 저장 키(siem_ref_key 형태). 원래 형태 "<_index>/<_id>"가 아니다. <_index>/<_id>를 JSON 문자열 이스케이프(ensure_ascii)하고 양쪽 따옴표를 뺀 값이다(D-049, soc.ids.siem_ref_key). 근거 ID가 아니라 발급 전 문서를 가리킨다
   */
  siem_refs: string[];
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  decided_at: number;
}
