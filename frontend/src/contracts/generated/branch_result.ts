/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface BranchResult {
  branch_id: string;
  subject_type: 'alert' | 'ticket';
  subject_id: string;
  path:
    | 'deduplicated'
    | 'excluded_shared_entity'
    | 'scenario_ticket'
    | 'l1_entity_lookup'
    | 'existing_incident'
    | 'new_incident';
  reason:
    | {
        rule_id: string;
      }
    | {
        entity: Entity;
      };
  created_at: number;
}
export interface Entity {
  type: string;
  value: string;
}
