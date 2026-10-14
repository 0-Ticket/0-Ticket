/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface VectorDoc {
  doc_id: string;
  collection: string;
  text: string;
  source_kind: 'ticket' | 'incident' | 'case' | 'asset' | 'alert' | 'event';
  source_id: string;
  keywords: string[];
  created_at: number;
  expires_at: number | null;
}
