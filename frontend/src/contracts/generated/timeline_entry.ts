/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface TimelineEntry {
  time: number;
  tactic: string | null;
  technique: string | null;
  description: string;
  /**
   * @minItems 1
   */
  evidence: [Evidence, ...Evidence[]];
}
export interface Evidence {
  ref_type: string;
  ref_id: string;
  note: string;
}
