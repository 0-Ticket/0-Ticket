import type { IncidentArtifact } from '../contracts';
import { registeredLabel, riskLabels, riskTones } from '../lib/display';
import { ObjectId, Timestamp } from './contract-display';
import { EvidenceList } from './evidence-list';
import { Icon } from './icon';
import { ToneBadge } from './ui/badge';
import { Section } from './ui/card';

const blockTitle = 'mb-3 text-xs font-bold tracking-wider text-muted-foreground uppercase';

// Strings here are LLM output or attacker-controlled values: text nodes only.
export function IncidentReport({ artifact }: { artifact: IncidentArtifact | null }) {
  return (
    <Section
      label="보고서"
      description="L2가 만든 사고 보고서"
      action={
        artifact && (
          <p className="text-xs text-muted-foreground">
            생성: <Timestamp value={artifact.generated_at} />
          </p>
        )
      }
      bodyClassName={artifact ? 'p-0 space-y-0' : undefined}
    >
      {artifact ? (
        <>
          <div className="border-b border-border px-4 py-3">
            <p
              className={
                artifact.needs_human
                  ? 'flex items-start gap-2 rounded-md border border-purple/30 bg-purple-soft px-3 py-2 text-sm font-semibold whitespace-pre-wrap break-words'
                  : 'text-sm break-words text-muted-foreground'
              }
            >
              사람 확인 {artifact.needs_human ? '필요' : '불필요'} ·{' '}
              {artifact.human_reason ?? '없음'}
            </p>
          </div>
          <div className="grid min-w-0 lg:grid-cols-[minmax(0,1.7fr)_minmax(240px,0.8fr)]">
            <div className="min-w-0 divide-y divide-border px-4 lg:border-r lg:border-border">
              <div className="py-4">
                <h3 className={blockTitle}>타임라인</h3>
                {artifact.timeline.length ? (
                  // The contract guarantees chronological order; keep the response order.
                  <ol className="relative space-y-4 before:absolute before:top-2 before:bottom-2 before:left-[4px] before:w-px before:bg-border">
                    {artifact.timeline.map((entry, index) => (
                      <li
                        key={index}
                        data-testid="timeline-entry"
                        data-time={entry.time}
                        className="relative min-w-0 space-y-1.5 pl-6"
                      >
                        <span
                          aria-hidden="true"
                          className="absolute top-1.5 left-0 size-[9px] rounded-full border-2 border-card bg-info shadow-[0_0_0_1px_var(--border-strong)]"
                        />
                        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs">
                          <span className="font-mono text-faint-foreground">
                            <Timestamp value={entry.time} />
                          </span>
                          <p className="font-mono text-muted-foreground">
                            전술 {entry.tactic ?? '없음'} · 기법 {entry.technique ?? '없음'}
                          </p>
                        </div>
                        <p className="text-sm whitespace-pre-wrap break-words">
                          {entry.description}
                        </p>
                        <EvidenceList
                          label={`타임라인 근거 ${index + 1}`}
                          evidence={entry.evidence}
                        />
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="text-sm text-muted-foreground">없음</p>
                )}
              </div>
              <div className="py-4">
                <h3 className={blockTitle}>IOC</h3>
                {artifact.iocs.length ? (
                  <ul className="space-y-1.5">
                    {artifact.iocs.map((ioc, index) => (
                      <li
                        key={index}
                        className="grid min-w-0 grid-cols-[minmax(4rem,auto)_minmax(0,1fr)] items-center gap-2 rounded-md border border-border bg-muted px-2.5 py-1.5"
                      >
                        <ToneBadge>{registeredLabel(ioc.type)}</ToneBadge>
                        {/* URLs are copyable text, never links. */}
                        <ObjectId value={ioc.value} />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">없음</p>
                )}
              </div>
              <div className="py-4">
                <h3 className={blockTitle}>추정 원인</h3>
                <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">
                  {artifact.suspected_cause}
                </p>
              </div>
            </div>
            <aside className="min-w-0 bg-muted px-4 py-4">
              <h3 className={blockTitle}>영향 자산</h3>
              {artifact.affected_assets.length ? (
                <ul className="space-y-1.5">
                  {artifact.affected_assets.map((asset, index) => (
                    <li
                      key={index}
                      className="flex min-w-0 items-center gap-2 rounded-md border border-border bg-card px-2.5 py-2 text-sm"
                    >
                      <Icon name="server" size={14} className="text-faint-foreground" />
                      <span className="min-w-0 font-mono break-all">{asset}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">없음</p>
              )}
            </aside>
          </div>
          <div className="border-t border-border px-4 py-4">
            <h3 className={blockTitle}>권고 조치</h3>
            {artifact.recommendations.length ? (
              <ul className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {artifact.recommendations.map((item, index) => (
                  <li
                    key={index}
                    className="min-w-0 space-y-2 rounded-md border border-border bg-muted p-3"
                  >
                    <ToneBadge>권고 · 실행하지 않음</ToneBadge>
                    <p className="text-sm whitespace-pre-wrap break-words">{item.action}</p>
                    <ToneBadge tone={riskTones[item.risk] ?? 'neutral'}>
                      위험 {riskLabels[item.risk] ?? item.risk} · 되돌릴 수{' '}
                      {item.reversible ? '있음' : '없음'}
                    </ToneBadge>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">없음</p>
            )}
          </div>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">없음</p>
      )}
    </Section>
  );
}
