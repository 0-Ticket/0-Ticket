/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

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
