/* Generated. Do not edit. Run pnpm contracts. */

/**
 * 사람 검토가 읽는 L2 Incident 분석 결과
 */
export type IncidentArtifact = {
  id: string;
  incident_id: string;
  analysis_round: number;
  verdict: "not_threat" | "attempted" | "succeeded" | "inconclusive";
  summary: string;
  /**
   * OCSF severity_id. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal
   */
  assessed_severity: number;
  timeline: {
    /**
     * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
     */
    time: number;
    summary: string;
    /**
     * @minItems 1
     *
     * Items: 판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID
     */
    evidence_ids: [string, ...string[]];
  }[];
  techniques: {
    id: string;
    name: string;
    /**
     * @minItems 1
     *
     * Items: 판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID
     */
    evidence_ids: [string, ...string[]];
  }[];
  impact: string;
  cause: string;
  further_risk: string;
  /**
   * Items: 판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID
   */
  evidence_ids: string[];
  /**
   * UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)
   */
  created_at: number;
};
