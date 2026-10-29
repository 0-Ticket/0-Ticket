/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface RuleProposal {
  proposal_id: string;
  hunt_id: string | null;
  case_id: string | null;
  title: string;
  techniques: string[];
  sigma_rule: string;
  siem_query: string | null;
  syntax_ok: boolean;
  backtest: Backtest | null;
  status: 'draft' | 'approved' | 'rejected' | 'deployed';
  reviewer: string | null;
  needs_human: boolean;
  human_reason: string | null;
  created_at: number;
}
export interface Backtest {
  window_start_at: number;
  window_end_at: number;
  attack_hits: number;
  benign_hits: number;
}
