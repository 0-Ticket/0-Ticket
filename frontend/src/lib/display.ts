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
};
export const registeredLabel = (value: string) =>
  Object.hasOwn(registered, value) ? registered[value] : value;
export const localTime = (value: number) => new Date(value).toLocaleString();
