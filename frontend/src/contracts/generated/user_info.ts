/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface UserInfo {
  user: string;
  dept: string | null;
  privileged: boolean;
  extensions: {
    [k: string]: unknown;
  };
}
