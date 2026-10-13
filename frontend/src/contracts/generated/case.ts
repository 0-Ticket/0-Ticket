/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface Case {
  case_id: string;
  incident_id: string;
  title: string;
  status: 'open' | 'responding' | 'closed';
  tasks: CaseTask[];
  lessons: string | null;
  extensions: {
    [k: string]: unknown;
  };
  created_at: number;
  closed_at: number | null;
}
export interface CaseTask {
  task: string;
  owner: string;
  due_at: number | null;
  status: 'todo' | 'doing' | 'done';
}
