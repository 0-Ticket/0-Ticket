/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */

export interface AliasTable {
  tool: string;
  log_type: string;
  mapping_profile: string;
  kind: 'alert' | 'event';
  class_uid: number | null;
  activity: string | null;
  fields: {
    [k: string]: string[];
  };
  time_format: string;
  severity_map: {
    [k: string]: number;
  } | null;
  default_techniques: string[] | null;
  extensions_map: {
    [k: string]: string;
  } | null;
  parse: {
    field: string;
    pattern: string;
  } | null;
}
