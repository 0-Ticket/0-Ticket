/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface EventRecord {
  event_id: string;
  source_record_id: string;
  class_uid: number;
  time: number;
  activity: string;
  src_ip: string | null;
  dst_ip: string | null;
  host: string | null;
  user: string | null;
  http_url: string | null;
  http_status: number | null;
  api_operation: string | null;
  status: string | null;
  src_asset: AssetInfo | null;
  dst_asset: AssetInfo | null;
  user_info: UserInfo | null;
  raw_ids: string[];
  unmapped: {
    [k: string]: unknown;
  };
  extensions: {
    [k: string]: unknown;
  };
}
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
export interface UserInfo {
  user: string;
  dept: string | null;
  privileged: boolean;
  extensions: {
    [k: string]: unknown;
  };
}
