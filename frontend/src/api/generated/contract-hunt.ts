/* Generated. Do not edit. Run pnpm contracts. */

/**
 * L3 가설 하나와 그 검증 결과. 같은 가설 생성 실행에서 나온 Hunt는 hunt_run_id로 묶는다
 */
export type Hunt = {
  id: string;
  /**
   * 같은 가설 생성 실행에서 나온 Hunt 묶음. Agent Log의 run_id(에이전트 실행 한 번)와 다른 ID다
   */
  hunt_run_id: string;
  /**
   * pending: 검증 대기(재시도 대기 포함), confirmed: 위협 발견(L3 Ticket을 만든다), rejected: 가설 기각, inconclusive: 근거 부족, failed: 검증 run이 재시도 한도까지 실패. 모두 L3가 바꾼다
   */
  status: "pending" | "confirmed" | "rejected" | "inconclusive" | "failed";
  /**
   * 가설 문장. 밖에서 온 문자열(뉴스 등)에서 나온 LLM 출력이라 공격자가 쓴 문장이 들어갈 수 있다
   */
  hypothesis: string;
  /**
   * ATT&CK 기법 ID(T1190, T1059.004). 중복 없음, 빈 목록 가능
   */
  attack_techniques: string[];
  /**
   * 검증 결과 확신도. confirmed, rejected, inconclusive일 때만 값이 있다
   */
  confidence: number | null;
  /**
   * 검증 결과 이유. confirmed, rejected, inconclusive일 때만 값이 있다. 공격자가 쓴 문장이 들어갈 수 있다
   */
  reason: string | null;
  /**
   * 검증 근거가 된 Alert·Event ID와 도구 호출 기록 ID. confirmed는 Alert·Event ID가 1개 이상, rejected는 1개 이상. 중복 없음
   *
   * Items: 판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID
   */
  evidence_ids: string[];
  /**
   * 검증에서 확인한 엔티티
   */
  entities: Entity[];
  /**
   * 검증 run 시도 횟수. pending이 아니면 1 이상
   */
  attempts: number;
  /**
   * 검증 결과가 정해진 시각. confirmed, rejected, inconclusive일 때만 값이 있다
   */
  verified_at: number | null;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  created_at: number;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  updated_at: number;
  /**
   * 가설 출처(뉴스·Case 참조) 등 L3 내부 값. 다른 단계는 읽지 않는다
   */
  details: {
    [k: string]: unknown;
  };
};

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
