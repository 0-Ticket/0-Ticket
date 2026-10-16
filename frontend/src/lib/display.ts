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
};
// Derived display only: documented screen rule for box 21, never a status value.
export const HUMAN_HANDLING_LABEL = '사람 직접 처리';
export const HUMAN_HANDLING_TONE: Tone = 'purple';
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
