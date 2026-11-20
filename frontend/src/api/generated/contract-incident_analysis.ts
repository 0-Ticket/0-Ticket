/* Generated. Do not edit. Run pnpm contracts. */

/**
 * L2 Incident 보고 run의 출력
 */
export interface IncidentAnalysis {
  verdict: "not_threat" | "attempted" | "succeeded" | "inconclusive";
  /**
   * 사건을 한 줄로 설명하는 제목. 길이·pattern을 두지 않는다: 빈 값이나 긴 값이 계약 오류가 되면 분석 전체가 실패해 같은 Incident를 다시 분석한다(D-059 유형). 저장할 때 soc.ticketing.clean_title로 정리하고, 정리 결과가 폴백이면 Incident 제목을 덮어쓰지 않는다(D-072)
   */
  title: string;
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
  /**
   * 권고 조치. 대응과 탐지 룰을 한 목록에 둔다(D-072). 한도를 넘으면 자르지 않고 거부한다
   *
   * @maxItems 10
   */
  recommendations:
    | []
    | [
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
      ]
    | [
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
      ]
    | [
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
      ]
    | [
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
      ]
    | [
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
      ]
    | [
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
      ]
    | [
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
      ]
    | [
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
      ]
    | [
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
      ]
    | [
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
        {
          kind: "response" | "detection";
          priority: "high" | "medium" | "low";
          /**
           * 한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern
           */
          title: string;
          /**
           * 구체적인 조치. 탐지 룰이면 룰 내용
           */
          detail: string;
          /**
           * 이 사건의 어떤 사실 때문에 필요한지
           */
          rationale: string;
        },
      ];
  /**
   * 어느 기법에도 붙지 않은 근거. 비어도 된다
   *
   * Items: 판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID
   */
  evidence_ids: string[];
}
