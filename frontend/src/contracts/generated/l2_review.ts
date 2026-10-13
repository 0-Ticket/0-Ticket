/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface L2Review {
  incident_id: string;
  reviewer: string;
  decision: 'approve' | 'reject';
  reject_type: 'wrong_grouping' | 'missing_step' | 'wrong_conclusion' | null;
  comment: string | null;
  round: number;
  created_at: number;
}
