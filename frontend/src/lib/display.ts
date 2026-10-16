export const badges: Record<string, { label: string; color: string }> = {
  new: { label: '신규', color: 'bg-accent' },
  triaging: {
    label: '분석 중',
    color: 'bg-blue-100 text-blue-950 dark:bg-blue-950 dark:text-blue-100',
  },
  awaiting_human: {
    label: '검토 대기',
    color: 'bg-amber-100 text-amber-950 dark:bg-amber-950 dark:text-amber-100',
  },
  closed_benign: { label: '정상 종결', color: 'bg-accent' },
  closed_fp: { label: '오탐 종결', color: 'bg-accent' },
  escalated: {
    label: '상위 분석',
    color: 'bg-red-100 text-red-950 dark:bg-red-950 dark:text-red-100',
  },
  tp: { label: 'TP', color: 'bg-red-100 text-red-950 dark:bg-red-950 dark:text-red-100' },
  fp: { label: 'FP', color: 'bg-accent' },
  unknown: { label: '불명', color: 'bg-accent' },
  open: { label: '열림', color: 'bg-accent' },
  investigating: {
    label: '조사 중',
    color: 'bg-blue-100 text-blue-950 dark:bg-blue-950 dark:text-blue-100',
  },
  escalated_to_case: {
    label: 'Case 전환',
    color: 'bg-red-100 text-red-950 dark:bg-red-950 dark:text-red-100',
  },
  correlation: { label: '규칙 묶음', color: 'bg-accent' },
  manual: {
    label: '사람이 직접 묶음',
    color: 'bg-amber-100 text-amber-950 dark:bg-amber-950 dark:text-amber-100',
  },
  l1: { label: 'L1 판정', color: 'bg-accent' },
  human_l1: {
    label: '사람 확정',
    color: 'bg-amber-100 text-amber-950 dark:bg-amber-950 dark:text-amber-100',
  },
  l3: { label: 'L3', color: 'bg-blue-100 text-blue-950 dark:bg-blue-950 dark:text-blue-100' },
  approve: { label: '승인', color: 'bg-accent' },
  reject: {
    label: '반려',
    color: 'bg-red-100 text-red-950 dark:bg-red-950 dark:text-red-100',
  },
  wrong_grouping: { label: '잘못된 묶음', color: 'bg-accent' },
  missing_step: { label: '누락된 단계', color: 'bg-accent' },
  wrong_conclusion: { label: '잘못된 결론', color: 'bg-accent' },
};
// Derived display only: documented screen rule for box 21, never a status value.
export const HUMAN_HANDLING_LABEL = '사람 직접 처리';
export const riskLabels: Record<string, string> = { low: '낮음', medium: '중간', high: '높음' };
export const severityLabels = [
  'Unknown',
  'Informational',
  'Low',
  'Medium',
  'High',
  'Critical',
  'Fatal',
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
