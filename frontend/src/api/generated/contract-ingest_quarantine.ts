/* Generated. Do not edit. Run pnpm contracts. */

/**
 * 수집한 문서 하나를 이유와 원문을 붙여 격리한 행
 */
export interface IngestQuarantine {
  siem_profile: string;
  source_kind: "alert" | "event";
  source_key: string;
  /**
   * 위치와 안정 해시를 담은 격리 전용 합성 키
   */
  siem_ref: string;
  reason_code: string;
  /**
   * 격리 전 원문을 json.dumps(ensure_ascii=True) 규칙으로 직렬화한 글자
   */
  original_text: string;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  seen_at: number;
}
