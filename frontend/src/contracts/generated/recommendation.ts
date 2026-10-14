/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface Recommendation {
  action: string;
  risk: 'low' | 'medium' | 'high';
  reversible: boolean;
}
