/* Generated. Do not edit. Run pnpm contracts. */

/**
 * 수집 대상 하나를 한 번 실행한 기록. 실행마다 하나씩 쌓인다
 */
export interface IngestRun {
  /**
   * 가져온 SIEM 연결 프로필 이름. IngestCheckpoint의 siem_profile과 같다
   */
  siem_profile: string;
  source_kind: "alert" | "event";
  /**
   * 설정에 적은 조회 대상. IngestCheckpoint의 source_key와 같다
   */
  source_key: string;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  started_at: number;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  finished_at: number;
  /**
   * 성공이면 ok, 실패면 실패 원인의 종류 코드. 원문과 비밀은 넣지 않는다
   */
  outcome: string;
  /**
   * 저장까지 끝난 페이지 수. 빈 페이지는 세지 않는다
   */
  pages: number;
  /**
   * 이 실행에서 새로 저장한 원본 수. 이미 있던 문서는 세지 않는다
   */
  inserted: number;
}
