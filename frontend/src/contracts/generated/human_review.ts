/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface HumanReview {
  ticket_id: string;
  reviewer: string;
  decision: 'tp' | 'fp';
  overturned: boolean;
  reason: string | null;
  created_at: number;
}
