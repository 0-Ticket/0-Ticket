/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface CaseTask {
  task: string;
  owner: string;
  due_at: number | null;
  status: 'todo' | 'doing' | 'done';
}
