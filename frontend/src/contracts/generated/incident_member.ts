/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

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
