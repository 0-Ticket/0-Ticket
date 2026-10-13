/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface HuntFinding {
  hunt_id: string;
  hypothesis: string;
  techniques: string[];
  method: 'baseline' | 'hypothesis';
  query_summary: string;
  evidence: Evidence[];
  is_anomaly: boolean;
  incident_id: string | null;
  rule_candidate: boolean;
  needs_human: boolean;
  human_reason: string | null;
  created_at: number;
}
export interface Evidence {
  ref_type: string;
  ref_id: string;
  note: string;
}
