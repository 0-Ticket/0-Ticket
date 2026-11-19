/* Generated. Do not edit. Run pnpm contracts. */

/**
 * OCSF 1.9.0 이벤트 문서. 클래스는 저장한 7개(0 Base Event, 2003, 3002, 4001, 4002, 4003, 6003)다. 우리 쪽 값은 모두 details에 있다. 최상위 time은 활동 발생 시각이고 severity_id가 심각도다. DB 컬럼 time(start_time 우선)·summary(message)·ocsf_class(class_uid)는 ocsf에서 파생한다
 */
export interface Event {
  /**
   * OCSF 클래스. 0 Base Event, 2003 Compliance Finding, 3002 Authentication, 4001 Network Activity, 4002 HTTP Activity, 4003 DNS Activity, 6003 API Activity
   */
  class_uid: 0 | 2003 | 3002 | 4001 | 4002 | 4003 | 6003;
  /**
   * 활동 발생 시각(epoch 밀리초)
   */
  time: number;
  /**
   * OCSF 심각도. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal, 99 Other
   */
  severity_id: 0 | 1 | 2 | 3 | 4 | 5 | 6 | 99;
  /**
   * 한 줄 요약. 공백이 아닌 글자가 하나 이상 있어야 한다. DB 컬럼 summary가 여기서 파생된다
   */
  message: string;
  /**
   * 우리 쪽 값. OCSF 속성 이름과 같은 키를 두지 않는다. 아래 4개는 필수이고 그 밖의 값은 더 올 수 있다
   */
  details: {
    id: string;
    raw_id: string;
    entities: Entity[];
    assets: Asset[];
    [k: string]: unknown;
  };
  [k: string]: unknown;
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
