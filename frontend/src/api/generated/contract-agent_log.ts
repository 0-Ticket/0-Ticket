/* Generated. Do not edit. Run pnpm contracts. */

/**
 * 에이전트의 모델 호출·도구 호출 한 번. 같은 작업의 호출은 run_id로 묶고 seq로 순서를 둔다. 비밀 값은 넣지 않는다
 */
export type AgentLog = {
  id: string;
  run_id: string;
  stage: "l1" | "l2" | "l3";
  /**
   * alert는 L1 1차 판정
   */
  subject_type: "alert" | "ticket" | "incident" | "hunt";
  /**
   * 대상 ID. alert는 alt_, ticket은 tkt_, incident는 inc_, hunt는 hrn_(가설 생성 run) 또는 hnt_(검증 run) ID
   */
  subject_id: string;
  /**
   * 작업 안 순번. (run_id, seq)는 유일
   */
  seq: number;
  kind: "model" | "tool";
  /**
   * 모델 이름 또는 도구 이름
   */
  name: string;
  /**
   * 입력 전체(JSON 값). 공격자가 쓴 문자열이 들어갈 수 있다
   */
  input: {
    [k: string]: unknown;
  };
  /**
   * 출력 전체(JSON 값). 실패해 출력이 없으면 null
   */
  output: {
    [k: string]: unknown;
  };
  outcome: "ok" | "error";
  /**
   * 모델 호출만. 도구 호출은 null
   */
  tokens_in: number | null;
  /**
   * 모델 호출만. 도구 호출은 null
   */
  tokens_out: number | null;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  started_at: number;
  duration_ms: number;
  /**
   * 계약에 없는 값. 다른 단계는 읽지 않는다
   */
  details: {
    [k: string]: unknown;
  };
};
