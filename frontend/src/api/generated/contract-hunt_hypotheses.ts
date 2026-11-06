/* Generated. Do not edit. Run pnpm contracts. */

/**
 * L3 가설 생성 run의 출력. L3 내부 출력 계약이고 다른 단계는 읽지 않는다. 가설 문장은 밖에서 온 문자열(뉴스 등)에서 나온 LLM 출력이다
 */
export interface HuntHypotheses {
  /**
   * 가설 목록. 가설을 세우지 못하면 빈 목록
   */
  hypotheses: HuntHypothesis[];
}
export interface HuntHypothesis {
  /**
   * 가설 문장
   */
  hypothesis: string;
  /**
   * ATT&CK 기법 ID(T1190, T1059.004). 1개 이상, 중복 없음. 실제로 있는 기법인지는 L3 코드가 확인한다
   *
   * @minItems 1
   */
  attack_techniques: [string, ...string[]];
  /**
   * 참고한 뉴스(threat_news.id). 중복 없음. 입력에 없던 값은 L3 코드가 버린다
   */
  news_ids: number[];
  /**
   * 참고한 Case ID. 중복 없음. 입력에 없던 값은 L3 코드가 버린다
   */
  case_ids: string[];
}
