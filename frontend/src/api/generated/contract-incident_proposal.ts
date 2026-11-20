/* Generated. Do not edit. Run pnpm contracts. */

/**
 * L2 Artifact에서 분리해 저장한 권고 조치(대응 또는 탐지 룰). 분석 출력의 recommendations 한 항목이다(D-072)
 */
export interface IncidentProposal {
  id: string;
  artifact_id: string;
  kind: "response" | "detection";
  /**
   * 한 Artifact의 권고 조치 목록 전체의 순서(1부터)
   */
  seq: number;
  /**
   * 옛 구조에서 옮긴 행(마이그레이션 0202)은 null
   */
  priority: ("high" | "medium" | "low") | null;
  /**
   * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. 옛 행은 본문 첫 줄을 정리한 값
   */
  title: string;
  /**
   * 구체적인 조치. 탐지 룰이면 룰 내용. 길이 한도는 분석 출력 계약만 지킨다(옛 body가 더 길 수 있다)
   */
  detail: string;
  /**
   * 이 사건의 어떤 사실 때문에 필요한지. 옛 행은 null
   */
  rationale: string | null;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  created_at: number;
}
