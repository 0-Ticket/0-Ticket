// Display tones; badge text is always shown so color is never the only signal.
export type Tone = 'neutral' | 'critical' | 'warning' | 'success' | 'info' | 'purple';
// Left accent rail for cards, keyed by the same tones as badges.
export const toneRails: Record<Tone, string> = {
  neutral: 'border-l-border-strong',
  info: 'border-l-info',
  warning: 'border-l-warning',
  critical: 'border-l-critical',
  success: 'border-l-success',
  purple: 'border-l-purple',
};
export const badges: Record<string, { label: string; tone: Tone }> = {
  new: { label: '신규', tone: 'neutral' },
  triaging: { label: '분석 중', tone: 'info' },
  awaiting_human: { label: '검토 대기', tone: 'warning' },
  closed_benign: { label: '정상 종결', tone: 'success' },
  closed_fp: { label: '오탐 종결', tone: 'neutral' },
  escalated: { label: '상위 분석', tone: 'critical' },
  // C6 status and C23 decision of the v2 L1 flow; `l1_escalated` is also a C6 origin.
  on_hold: { label: '보류', tone: 'warning' },
  l2_escalated: { label: 'L2 승격', tone: 'critical' },
  l1_escalated: { label: 'L1 승격', tone: 'info' },
  held: { label: '보류', tone: 'warning' },
  // C6 origin (D-038).
  l3_escalated: { label: 'L3 승격', tone: 'purple' },
  scenario: { label: '시나리오', tone: 'neutral' },
  // C23 hold reason (D-036, D-034).
  below_threshold: { label: '확신도 미만', tone: 'warning' },
  llm_failure: { label: 'LLM 실패', tone: 'critical' },
  evidence_request_failure: { label: '증거 요청 실패', tone: 'critical' },
  // C21 branch path (boxes 10-13).
  deduplicated: { label: '중복 제거', tone: 'neutral' },
  excluded_shared_entity: { label: '공용 엔티티 제외', tone: 'neutral' },
  scenario_ticket: { label: '시나리오 티켓', tone: 'info' },
  l1_entity_lookup: { label: 'L1 엔티티 조회', tone: 'info' },
  existing_incident: { label: '기존 Incident 추가', tone: 'warning' },
  new_incident: { label: '새 Incident', tone: 'critical' },
  // C22 evidence request status (unnumbered queue).
  pending: { label: '대기', tone: 'neutral' },
  in_progress: { label: '진행 중', tone: 'info' },
  completed: { label: '완료', tone: 'success' },
  failed: { label: '실패', tone: 'critical' },
  tp: { label: 'TP', tone: 'critical' },
  fp: { label: 'FP', tone: 'neutral' },
  unknown: { label: '불명', tone: 'neutral' },
  open: { label: '열림', tone: 'neutral' },
  investigating: { label: '조사 중', tone: 'info' },
  escalated_to_case: { label: 'Case 전환', tone: 'critical' },
  correlation: { label: '규칙 묶음', tone: 'neutral' },
  manual: { label: '사람이 직접 묶음', tone: 'purple' },
  l1: { label: 'L1 판정', tone: 'neutral' },
  human_l1: { label: '사람 확정', tone: 'purple' },
  l3: { label: 'L3', tone: 'info' },
  approve: { label: '승인', tone: 'success' },
  reject: { label: '반려', tone: 'critical' },
  wrong_grouping: { label: '잘못된 묶음', tone: 'neutral' },
  missing_step: { label: '누락된 단계', tone: 'neutral' },
  wrong_conclusion: { label: '잘못된 결론', tone: 'neutral' },
  // C16 Case status (`open` shared above) and CaseTask status.
  responding: { label: '대응 중', tone: 'warning' },
  closed: { label: '종결', tone: 'success' },
  todo: { label: '할 일', tone: 'neutral' },
  doing: { label: '진행 중', tone: 'info' },
  done: { label: '완료', tone: 'success' },
  // C17 method.
  baseline: { label: '통계 기준선', tone: 'neutral' },
  hypothesis: { label: '가설 기반', tone: 'neutral' },
  // C18 status, shown as received. `approved` means reviewed, not applied to the SIEM.
  draft: { label: '초안', tone: 'warning' },
  approved: { label: '승인됨', tone: 'success' },
  rejected: { label: '반려됨', tone: 'neutral' },
  deployed: { label: '배포됨', tone: 'info' },
};
// C10 review_state (L2 review workflow), kept apart from the lifecycle `status` badges.
export const reviewStateBadges: Record<string, { label: string; tone: Tone }> = {
  analyzing: { label: 'L2 분석 중', tone: 'info' },
  awaiting_review: { label: 'L2 검토 대기', tone: 'warning' },
  approved: { label: 'L2 승인', tone: 'success' },
  human_handling: { label: '사람 직접 처리', tone: 'purple' },
};
// C22 request_type (unnumbered queue). The specialist `domain` stays a registered value.
export const requestTypeLabels: Record<string, string> = {
  specialist_agent: '전문가 Agent',
  siem_mcp: 'SIEM MCP',
  lookup: 'Lookup',
};
export const riskLabels: Record<string, string> = { low: '낮음', medium: '중간', high: '높음' };
export const riskTones: Record<string, Tone> = {
  low: 'neutral',
  medium: 'warning',
  high: 'critical',
};
export const severityLabels = [
  'Unknown',
  'Informational',
  'Low',
  'Medium',
  'High',
  'Critical',
  'Fatal',
];
// Indexed by severity_id (0 ~ 6), alongside severityLabels.
export const severityTones: Tone[] = [
  'neutral',
  'neutral',
  'info',
  'info',
  'warning',
  'critical',
  'critical',
];
const registered: Record<string, string> = {
  web_attack: '웹 공격',
  scan: '스캔',
  cloud: '클라우드',
  other: '기타',
  none: '없음',
  web: '웹',
  ip: 'IP',
  host: '호스트',
  user: '계정',
  domain: '도메인',
  url: 'URL',
  hash: '해시',
};
export const registeredLabel = (value: string) =>
  Object.hasOwn(registered, value) ? registered[value] : value;
export const localTime = (value: number) => new Date(value).toLocaleString();
