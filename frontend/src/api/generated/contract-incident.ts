/* Generated. Do not edit. Run pnpm contracts. */

/**
 * 같은 공격으로 보이는 Ticket들의 묶음. L2 분석과 사람 검토의 단위
 */
export interface Incident {
  id: string;
  /**
   * L2가 정한 제목
   */
  title: string;
  /**
   * 분석 요약. L2가 채운다. 분석 전 null
   */
  summary: string | null;
  /**
   * analyzing: L2 분석 필요·중, held: L2 연속 실패 소진 후 쿨다운 대기, awaiting_review: 사람 검토 대기, confirmed: 사람 승인(Case 생성), human_handling: 사람이 직접 처리, dismissed: 위협 아님으로 종결(L2가 분석 후, 또는 사람이 검토 중이나 직접 처리를 끝낼 때)
   */
  status:
    | "analyzing"
    | "awaiting_review"
    | "confirmed"
    | "human_handling"
    | "dismissed"
    | "held";
  /**
   * 1개 이상. 중복 없음
   *
   * @minItems 1
   */
  ticket_ids: [string, ...string[]];
  /**
   * 소속 Ticket 엔티티와 L2 조사에서 근거와 함께 확인한 엔티티를 모은 것
   */
  entities: Entity[];
  /**
   * 소속 Alert 심각도 중 최대. 소속 Alert가 없으면 0
   */
  severity: number;
  /**
   * L2 분석이 판단한 심각도. 분석 전 null
   */
  assessed_severity: number | null;
  /**
   * L2 분석 시도 순번. 성공·실패마다 증가하고 취소에는 증가하지 않는다
   */
  analysis_round: number;
  /**
   * 사람 검토 횟수
   */
  review_round: number;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  created_at: number;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  updated_at: number;
  /**
   * 계약에 없는 값. 다른 단계는 읽지 않는다
   */
  details: {
    [k: string]: unknown;
  };
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
