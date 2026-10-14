/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface AssetInfo {
  match: string;
  hostname: string;
  criticality: number;
  owner: string | null;
  zone: string | null;
  shared: boolean;
  valid_from: number | null;
  valid_to: number | null;
  extensions: {
    [k: string]: unknown;
  };
}
