/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface AlertRecord {
  alert_id: string;
  source_record_id: string;
  class_uid: 2004;
  time: number;
  severity_id: number;
  rule_id: string;
  rule_name: string;
  src_ip: string | null;
  src_port: number | null;
  dst_ip: string | null;
  dst_port: number | null;
  host: string | null;
  user: string | null;
  http_url: string | null;
  http_status: number | null;
  techniques: string[];
  raw_ids: string[];
  unmapped: {
    [k: string]: unknown;
  };
  extensions: {
    [k: string]: unknown;
  };
  src_asset: AssetInfo | null;
  dst_asset: AssetInfo | null;
  user_info: UserInfo | null;
  count: number;
  first_seen: number;
  last_seen: number;
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
