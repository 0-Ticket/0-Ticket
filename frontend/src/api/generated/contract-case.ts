/* Generated. Do not edit. Run pnpm contracts. */

/**
 * 사람이 확정한 Incident. 승인 시점 내용을 복사해 둔다
 */
export interface Case {
  id: string;
  incident_id: string;
  /**
   * 승인 시점 Incident 제목
   */
  title: string;
  /**
   * 승인 시점 Incident summary를 그대로 복사
   */
  summary: string | null;
  /**
   * 승인 시점 assessed_severity, 없으면 severity
   */
  severity: number;
  /**
   * 승인 시점 엔티티
   */
  entities: Entity[];
  /**
   * 승인한 사람
   */
  confirmed_by: string;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  confirmed_at: number;
  /**
   * open → in_progress → resolved. 사람이 화면에서 바꾼다
   */
  status: "open" | "in_progress" | "resolved";
  /**
   * 담당 분석가
   */
  assignee: string | null;
  /**
   * status가 resolved이면 필수, 그 밖에는 null
   */
  resolved_at: number | null;
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
