/* Generated. Do not edit. Run pnpm contracts. */

/**
 * 수집 대상 하나의 재개 위치. (siem_profile, source_kind, source_key)마다 하나다
 */
export interface IngestCheckpoint {
  /**
   * 가져온 SIEM 연결 프로필 이름. RawRecord의 siem_profile과 같다
   */
  siem_profile: string;
  source_kind: "alert" | "event";
  /**
   * 설정에 적은 조회 대상. ELK는 alias 또는 인덱스·데이터 스트림 패턴
   */
  source_key: string;
  /**
   * 다음 실행이 이어서 조회할 위치. 안쪽 모양은 수집기가 정한다(예: {"time_ms": 1730000000000})
   */
  cursor: {
    [k: string]: unknown;
  };
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  updated_at: number;
}
