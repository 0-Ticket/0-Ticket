/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface SiemAlert {
  kind: 'alert' | 'event';
  scenario: string;
  raw_ids: string[];
  fields: {
    [k: string]: unknown;
  };
}
