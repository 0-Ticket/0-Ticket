/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface EvidenceRequest {
  request_id: string;
  requester_type: 'ticket' | 'incident';
  requester_id: string;
  request_type: 'specialist_agent' | 'siem_mcp' | 'lookup';
  domain: string | null;
  retry_count: number;
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
  failure_reason: string | null;
  created_at: number;
  updated_at: number;
}
