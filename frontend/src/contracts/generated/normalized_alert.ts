/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface NormalizedAlert {
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
}
