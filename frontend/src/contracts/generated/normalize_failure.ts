/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface NormalizeFailure {
  scenario: string;
  raw_ids: string[];
  reason: 'unknown_scenario' | 'missing_required' | 'bad_value';
  missing_fields: string[];
  detail: string | null;
  failed_at: number;
}
