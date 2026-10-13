/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface Ticket {
  ticket_id: string;
  status: 'new' | 'triaging' | 'awaiting_human' | 'closed_benign' | 'closed_fp' | 'escalated';
  handling_type: string;
  specialist: string;
  priority: number;
  /**
   * @minItems 1
   */
  alert_ids: [string, ...string[]];
  entities: Entity[];
  verdict: Verdict | null;
  extensions: {
    [k: string]: unknown;
  };
  created_at: number;
  updated_at: number;
}
export interface Entity {
  type: string;
  value: string;
}
export interface Verdict {
  verdict: 'tp' | 'fp' | 'unknown';
  confidence: number;
  summary: string;
  /**
   * @minItems 1
   */
  evidence: [Evidence, ...Evidence[]];
  recommended_action: string;
  needs_human: boolean;
  human_reason: string | null;
}
export interface Evidence {
  ref_type: string;
  ref_id: string;
  note: string;
}
