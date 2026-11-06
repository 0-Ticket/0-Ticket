/* Generated. Do not edit. Run pnpm contracts. */

/**
 * L2 Artifact에서 분리해 저장한 탐지 또는 대응 제안
 */
export interface IncidentProposal {
  id: string;
  artifact_id: string;
  kind: "detection_rule" | "response_action";
  seq: number;
  body: string;
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  created_at: number;
}
