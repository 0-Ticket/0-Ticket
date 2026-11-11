/* Generated. Do not edit. Run pnpm contracts. */

/**
 * SIEM에서 가져온 Alert·Event 원본. 바꾸지 않고 그대로 보관한다
 */
export interface RawRecord {
  id: string;
  kind: "alert" | "event";
  /**
   * 가져온 SIEM 연결 프로필 이름
   */
  siem_profile: string;
  /**
   * SIEM 안에서 문서 하나를 가리키는 값. ELK는 <_index>/<_id>
   */
  siem_ref: string;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  fetched_at: number;
  /**
   * SIEM이 준 JSON 그대로, json.dumps(ensure_ascii=True) 글자. 되살릴 때는 json.loads를 쓴다(D-049)
   */
  original_text: string;
}
