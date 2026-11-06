/* Generated. Do not edit. Run pnpm contracts. */

/**
 * OCSF 1.9.0으로 정규화한 이벤트. 맞는 클래스가 없으면 Base Event(class_uid 0)
 */
export interface Event {
  id: string;
  raw_id: string;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  time: number;
  /**
   * OCSF class_uid. ocsf.class_uid와 같아야 한다(validate_contract 추가 검사)
   */
  ocsf_class: number;
  /**
   * 한 줄 요약
   */
  summary: string;
  entities: Entity[];
  assets: Asset[];
  /**
   * 매핑한 OCSF 클래스 전체
   */
  ocsf: {
    class_uid: number;
    [k: string]: unknown;
  };
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
/**
 * Lookup으로 붙인 자산 정보
 */
export interface Asset {
  /**
   * 어느 엔티티의 자산 정보인지. 조회에 쓴 정규화 키(Entity.type, 정규화한 Entity.value)
   */
  entity: {
    /**
     * 엔티티 종류
     */
    type: "ip" | "host" | "user" | "domain" | "url" | "file_hash" | "process";
    /**
     * 엔티티 값
     */
    value: string;
  };
  /**
   * 자산 이름
   */
  name: string | null;
  /**
   * 중요도 1~5. 5가 가장 중요
   */
  criticality: number | null;
  /**
   * 담당 부서·사람
   */
  owner: string | null;
}
