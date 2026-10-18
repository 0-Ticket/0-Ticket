/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface L1DecisionRecord {
  decision_id: string;
  subject_type: 'alert' | 'ticket';
  subject_id: string;
  decision: 'l1_escalated' | 'held' | 'closed_fp' | 'l2_escalated';
  confidence: number | null;
  reason: 'below_threshold' | 'llm_failure' | 'evidence_request_failure' | null;
  created_at: number;
}
