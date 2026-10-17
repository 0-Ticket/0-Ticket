import { useParams } from 'react-router';
import { useHunt } from '../api/hunt-queries';
import { AgentLog } from '../components/agent-log';
import { ObjectId, QueryError, StatusNote, Timestamp } from '../components/contract-display';
import { EvidenceList } from '../components/evidence-list';
import { HuntBadges, HuntIncident } from '../components/hunt-list';
import { Breadcrumbs } from '../components/page-header';
import { MetaLabel, Section } from '../components/ui/card';
import { severityTones, toneRails } from '../lib/display';
import { cn } from '../lib/utils';

export function HuntDetailPage() {
  const { hunt_id = '' } = useParams();
  const query = useHunt(hunt_id);
  const detail = query.data;
  const hunt = detail?.hunt;
  return (
    <div>
      {query.isPending && <StatusNote busy>헌팅 상세 불러오는 중…</StatusNote>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void query.refetch()}
        />
      )}
      {detail && hunt && (
        <>
          <Breadcrumbs list="헌팅 결과" to="/hunts" current={hunt.hunt_id} />
          <header
            className={cn(
              'min-w-0 space-y-3 rounded-lg border border-l-4 border-border bg-card p-4 shadow-card',
              toneRails[severityTones[hunt.severity_id] ?? 'neutral'],
            )}
          >
            <HuntBadges hunt={hunt} />
            <h1 className="text-xl font-semibold tracking-tight break-all">헌팅 {hunt.hunt_id}</h1>
            <ObjectId value={hunt.hunt_id} />
            <div>
              <MetaLabel>가설</MetaLabel>
              <p className="text-lg font-medium whitespace-pre-wrap break-words">
                {hunt.hypothesis}
              </p>
            </div>
            {hunt.needs_human && (
              <div className="rounded-md border border-purple/30 bg-purple-soft px-3 py-2 text-sm">
                <MetaLabel>사람 확인 사유</MetaLabel>
                <p className="whitespace-pre-wrap break-words">{hunt.human_reason ?? '없음'}</p>
              </div>
            )}
            <div className="grid gap-x-6 gap-y-1 border-t border-border pt-3 text-sm text-muted-foreground lg:grid-cols-3">
              <HuntIncident id={hunt.incident_id} />
              <p>룰 후보: {hunt.rule_candidate ? '예' : '아니오'}</p>
              <p>
                생성: <Timestamp value={hunt.created_at} />
              </p>
            </div>
          </header>
          <div className="mt-4 grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,400px)]">
            <div className="min-w-0 space-y-4">
              <Section label="헌팅 내용" description="가설과 관련 기법, 조회 방법, 찾은 근거">
                <div>
                  <MetaLabel>기법</MetaLabel>
                  {hunt.techniques.length ? (
                    <ul className="flex flex-wrap gap-2 font-mono text-xs">
                      {hunt.techniques.map((technique) => (
                        <li key={technique} className="rounded border border-border px-1.5 py-0.5">
                          {technique}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-muted-foreground">없음</p>
                  )}
                </div>
                <div>
                  <MetaLabel>조회 요약</MetaLabel>
                  <p className="text-sm whitespace-pre-wrap break-words">{hunt.query_summary}</p>
                </div>
                <EvidenceList evidence={hunt.evidence} label="근거" />
              </Section>
              <AgentLog steps={detail.steps} />
            </div>
            <aside className="min-w-0 space-y-4">
              <Section label="룰 제안" description="이 헌팅에서 나온 탐지 룰 제안">
                {detail.proposal_ids.length ? (
                  <ul className="space-y-1">
                    {detail.proposal_ids.map((id) => (
                      <li key={id}>
                        <ObjectId value={id} href={`/rules/${encodeURIComponent(id)}`} />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">없음</p>
                )}
              </Section>
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
