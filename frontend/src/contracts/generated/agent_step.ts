/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface AgentStep {
  subject_type: 'ticket' | 'incident' | 'hunt';
  subject_id: string;
  step: number;
  agent: string;
  action: 'llm_call' | 'tool_call' | 'decision';
  tool: string | null;
  prompt_version: string | null;
  input_excerpt: string;
  output_excerpt: string;
  model: string | null;
  tokens: number | null;
  latency_ms: number;
  created_at: number;
}
