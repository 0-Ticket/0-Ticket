/* Generated. Do not edit. Run pnpm contracts. */

/**
 * L2 Incident 보고 run의 출력
 */
export interface IncidentAnalysis {
  verdict: "not_threat" | "attempted" | "succeeded" | "inconclusive";
  summary: string;
  /**
   * OCSF severity_id. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal
   */
  assessed_severity: number;
  techniques: {
    id: string;
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
  detection_rules: string[];
  response_actions: string[];
  /**
   * 어느 기법에도 붙지 않은 근거. 비어도 된다
   *
   * Items: 판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID
   */
  evidence_ids: string[];
}
