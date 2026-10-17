import type { RuleProposal } from '../contracts';
import { badges, toneRails } from '../lib/display';
import { cn } from '../lib/utils';
import { Badge, ObjectId, Timestamp } from './contract-display';
import { ToneBadge } from './ui/badge';

// C18 status, syntax check and human flag shown as received.
export function RuleBadges({ rule }: { rule: RuleProposal }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge value={rule.status} />
      <ToneBadge tone={rule.syntax_ok ? 'success' : 'critical'}>
        {rule.syntax_ok ? '문법 검사 통과' : '문법 검사 실패'}
      </ToneBadge>
      {rule.needs_human && <ToneBadge tone="purple">사람 확인 필요</ToneBadge>}
    </div>
  );
}

// Only the references C18 carries (hunt_id, case_id). No other relation is derived here.
export function RuleBasis({ rule, prefix = '' }: { rule: RuleProposal; prefix?: string }) {
  const link = (label: string, id: string | null, path: string) =>
    id === null ? (
      <span>
        {prefix}
        {label}: 없음
      </span>
    ) : (
      <span className="flex flex-wrap items-center gap-1">
        {prefix}
        {label} <ObjectId value={id} href={`/${path}/${encodeURIComponent(id)}`} />
      </span>
    );
  return (
    <>
      {link('헌팅', rule.hunt_id, 'hunts')}
      {link('Case', rule.case_id, 'cases')}
    </>
  );
}

export function RuleList({ rules }: { rules: RuleProposal[] }) {
  return (
    <ol className="space-y-3">
      {rules.map((rule) => {
        const tone = Object.hasOwn(badges, rule.status) ? badges[rule.status].tone : 'neutral';
        return (
          <li key={rule.proposal_id}>
            <article
              data-testid="rule-row"
              className={cn(
                'min-w-0 overflow-hidden rounded-lg border border-l-4 border-border bg-card shadow-card',
                toneRails[tone],
              )}
            >
              <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border px-4 py-2.5">
                <ObjectId
                  value={rule.proposal_id}
                  href={`/rules/${encodeURIComponent(rule.proposal_id)}`}
                />
                <RuleBadges rule={rule} />
              </header>
              <div className="grid min-w-0 gap-4 px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto]">
                <div className="min-w-0 space-y-1">
                  <p className="font-semibold whitespace-pre-wrap break-words">{rule.title}</p>
                  <p className="text-xs break-words text-muted-foreground">
                    기법: {rule.techniques.length ? rule.techniques.join(', ') : '없음'}
                  </p>
                  <div className="space-y-0.5 text-xs text-muted-foreground">
                    <RuleBasis rule={rule} />
                  </div>
                </div>
                <div className="space-y-1 text-xs text-muted-foreground md:min-w-56 md:border-l md:border-border md:pl-4">
                  <p className="whitespace-pre-wrap break-words">
                    검토자: {rule.reviewer ?? '없음'}
                  </p>
                  <p>
                    {rule.backtest === null
                      ? '백테스트: 없음'
                      : `백테스트: 공격 구간 ${rule.backtest.attack_hits}건 · 정상 구간 ${rule.backtest.benign_hits}건`}
                  </p>
                  <p>
                    생성 <Timestamp value={rule.created_at} />
                  </p>
                </div>
              </div>
            </article>
          </li>
        );
      })}
    </ol>
  );
}
