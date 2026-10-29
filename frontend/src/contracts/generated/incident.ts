/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface Incident {
  incident_id: string;
  title: string;
  status: 'open' | 'investigating' | 'closed_benign' | 'escalated_to_case';
  created_by: 'correlation' | 'manual';
  severity_id: number;
  first_seen: number;
  last_seen: number;
  tactics: string[];
  summary: string | null;
  members: IncidentMember[];
  review_state: 'analyzing' | 'awaiting_review' | 'approved' | 'human_handling';
  review_round: number | null;
  extensions: {
    [k: string]: unknown;
  };
}
export interface IncidentMember {
  member_type: 'ticket' | 'hunt';
  ticket_id: string | null;
  hunt_id: string | null;
  source: 'l1' | 'human_l1' | 'l3';
  rule: string;
  matched_entity: Entity | null;
  excluded: boolean;
  excluded_reason: string | null;
}
export interface Entity {
  type: string;
  value: string;
}
