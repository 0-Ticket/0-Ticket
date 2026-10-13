/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface SpecialistFinding {
  ticket_id: string;
  specialist: string;
  question: string;
  summary: string;
  attack_type: string | null;
  succeeded: 'yes' | 'no' | 'unknown';
  confidence: number;
  /**
   * @minItems 1
   */
  evidence: [Evidence, ...Evidence[]];
  details: {
    [k: string]: unknown;
  };
  needs_human: boolean;
  human_reason: string | null;
  created_at: number;
}
export interface Evidence {
  ref_type: string;
  ref_id: string;
  note: string;
}
