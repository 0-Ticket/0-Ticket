/* Generated. Do not edit. Run pnpm contracts. */

/**
 * L2 Ticket 분류 run의 출력. 어느 DB 레코드에도 그대로 저장하지 않는다
 */
export type BranchDecision = {
  /**
   * 새 Incident를 만들지, 입력 후보 하나에 붙일지
   */
  decision: "new" | "existing";
  /**
   * existing이면 후보 Incident ID, new이면 null. 실제 후보인지는 코드가 확인한다
   */
  incident_id: string | null;
  /**
   * 분류 확신도. 기록만 하고 판정 임계로 쓰지 않는다
   */
  confidence: number;
  /**
   * 분류 이유
   */
  reason: string;
  /**
   * 입력에 보인 비슷한 Ticket ID의 부분집합. 실제 부분집합인지는 코드가 확인한다
   */
  similar_ticket_ids: string[];
};
