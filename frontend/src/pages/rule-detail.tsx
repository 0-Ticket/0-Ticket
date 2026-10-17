import { useParams } from 'react-router';
import type { ReactNode } from 'react';
import { useCase } from '../api/case-queries';
import { useHunt } from '../api/hunt-queries';
import { useRule } from '../api/rule-queries';
import type { RuleProposal } from '../contracts';
import { ObjectId, QueryError, StatusNote, Timestamp } from '../components/contract-display';
import { HuntIncident } from '../components/hunt-list';
import { Breadcrumbs } from '../components/page-header';
import { RuleBadges, RuleBasis } from '../components/rule-list';
import { RuleReview } from '../components/rule-review';
import { MetaLabel, Section } from '../components/ui/card';
import { badges, toneRails } from '../lib/display';
import { cn } from '../lib/utils';

// Rule text is attacker- or LLM-influenced: a monospace block of plain text, no highlighting.
const code =
  'max-h-96 overflow-auto rounded-md border border-[#26323d] bg-[#0a0f14] p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-[#c1cbd6] [overflow-wrap:anywhere]';

function RelatedIncidentFrame({
  source,
  query,
  incidentId,
}: {
  source: ReactNode;
  query: { isPending: boolean; isFetching: boolean; error: Error | null; refetch: () => unknown };
  incidentId: string | null | undefined;
}) {
  return (
    <Section label="관련 Incident" description="근거 객체에 기록된 Incident">
      <p className="text-xs text-muted-foreground">{source}</p>
      {incidentId !== undefined && (
        <p className="text-sm">
          <HuntIncident id={incidentId} />
        </p>
      )}
      {query.isPending && <StatusNote busy>근거 불러오는 중…</StatusNote>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void query.refetch()}
        />
      )}
    </Section>
  );
}

// C18 has no incident_id. Follow its own reference through the existing detail Query (same
// key as F4/F5) and show only the incident_id that API returns; nothing is copied into C18.
function IncidentFromHunt({ id }: { id: string }) {
  const query = useHunt(id);
  return (
    <RelatedIncidentFrame
      source={`근거 헌팅 ${id}에 기록된 incident_id`}
      query={query}
      incidentId={query.data?.hunt.incident_id}
    />
  );
}
function IncidentFromCase({ id }: { id: string }) {
  const query = useCase(id);
  return (
    <RelatedIncidentFrame
      source={`근거 Case ${id}에 기록된 incident_id`}
      query={query}
      incidentId={query.data?.case.incident_id}
    />
  );
}
function RelatedIncident({ rule }: { rule: RuleProposal }) {
  if (rule.hunt_id !== null) return <IncidentFromHunt id={rule.hunt_id} />;
  if (rule.case_id !== null) return <IncidentFromCase id={rule.case_id} />;
  return null;
}

export function RuleDetailPage() {
  const { proposal_id = '' } = useParams();
  const query = useRule(proposal_id);
  const rule = query.data;
  const tone = rule && Object.hasOwn(badges, rule.status) ? badges[rule.status].tone : 'neutral';
  return (
    <div>
      {query.isPending && <StatusNote busy>룰 제안 상세 불러오는 중…</StatusNote>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void query.refetch()}
        />
      )}
      {rule && (
        <>
          <Breadcrumbs list="룰 제안 목록" to="/rules" current={rule.proposal_id} />
          <header
            className={cn(
              'min-w-0 space-y-3 rounded-lg border border-l-4 border-border bg-card p-4 shadow-card',
              toneRails[tone],
            )}
          >
            <RuleBadges rule={rule} />
            <h1 className="text-xl font-semibold tracking-tight break-all">
              룰 제안 {rule.proposal_id}
            </h1>
            <ObjectId value={rule.proposal_id} />
            <p className="text-lg font-medium whitespace-pre-wrap break-words">{rule.title}</p>
            {rule.needs_human && (
              <div className="rounded-md border border-purple/30 bg-purple-soft px-3 py-2 text-sm">
                <MetaLabel>사람 확인 사유</MetaLabel>
                <p className="whitespace-pre-wrap break-words">{rule.human_reason ?? '없음'}</p>
              </div>
            )}
            <div className="grid gap-x-6 gap-y-1 border-t border-border pt-3 text-sm text-muted-foreground lg:grid-cols-2">
              <RuleBasis rule={rule} prefix="근거 " />
              <p className="whitespace-pre-wrap break-words">검토자: {rule.reviewer ?? '없음'}</p>
              <p>
                생성: <Timestamp value={rule.created_at} />
              </p>
            </div>
            <div>
              <MetaLabel>기법</MetaLabel>
              {rule.techniques.length ? (
                <ul className="flex flex-wrap gap-2 font-mono text-xs">
                  {rule.techniques.map((technique) => (
                    <li key={technique} className="rounded border border-border px-1.5 py-0.5">
                      {technique}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">없음</p>
              )}
            </div>
          </header>
          <div className="mt-4 grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,400px)]">
            <div className="min-w-0 space-y-4">
              <Section label="Sigma 룰" description="제안된 Sigma 룰 원문">
                <pre className={code}>{rule.sigma_rule}</pre>
              </Section>
              <Section label="SIEM 쿼리" description="연결된 SIEM 쿼리로 변환한 결과">
                {rule.siem_query === null ? (
                  <p className="text-sm text-muted-foreground">없음</p>
                ) : (
                  <pre className={code}>{rule.siem_query}</pre>
                )}
              </Section>
              <Section label="백테스트" description="코어가 돌린 결과를 받은 그대로 표시">
                {rule.backtest === null ? (
                  <p className="text-sm text-muted-foreground">없음</p>
                ) : (
                  <dl className="grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[minmax(8rem,auto)_minmax(0,1fr)]">
                    <dt className="text-muted-foreground">기간 시작</dt>
                    <dd>
                      <Timestamp value={rule.backtest.window_start_at} />
                    </dd>
                    <dt className="text-muted-foreground">기간 끝</dt>
                    <dd>
                      <Timestamp value={rule.backtest.window_end_at} />
                    </dd>
                    <dt className="text-muted-foreground">공격 구간 탐지 건수</dt>
                    <dd className="tabular-nums">{rule.backtest.attack_hits}</dd>
                    <dt className="text-muted-foreground">정상 구간 오탐 건수</dt>
                    <dd className="tabular-nums">{rule.backtest.benign_hits}</dd>
                  </dl>
                )}
              </Section>
              <RelatedIncident rule={rule} />
            </div>
            <aside className="min-w-0 space-y-4">
              <RuleReview key={rule.proposal_id} rule={rule} refreshFailed={query.isError} />
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
