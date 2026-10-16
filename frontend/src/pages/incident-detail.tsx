import { useParams } from 'react-router';
import { useIncident } from '../api/incident-queries';
import {
  Badge,
  Extensions,
  ObjectId,
  QueryError,
  ReviewStateBadge,
  StatusNote,
  Timestamp,
} from '../components/contract-display';
import { Breadcrumbs } from '../components/page-header';
import { ToneBadge } from '../components/ui/badge';
import { Section } from '../components/ui/card';
import { cn } from '../lib/utils';
import { EvidenceList } from '../components/evidence-list';
import { AgentLog } from '../components/agent-log';
import { IncidentMembers } from '../components/incident-members';
import { IncidentReport } from '../components/incident-report';
import { IncidentReview } from '../components/incident-review';
import { TicketList } from '../components/ticket-list';
import { severityTones, toneRails } from '../lib/display';

export function IncidentDetailPage() {
  const { incident_id = '' } = useParams();
  const query = useIncident(incident_id);
  const detail = query.data;
  const incident = detail?.incident;
  return (
    <div>
      {query.isPending && <StatusNote busy>Incident 상세 불러오는 중…</StatusNote>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void query.refetch()}
        />
      )}
      {detail && incident && (
        <>
          <Breadcrumbs list="Incident 목록" to="/incidents" current={incident.incident_id} />
          <header
            className={cn(
              'min-w-0 space-y-3 rounded-lg border border-l-4 border-border bg-card p-4 shadow-card',
              toneRails[severityTones[incident.severity_id] ?? 'neutral'],
            )}
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge value={null} severity={incident.severity_id} />
              <Badge value={incident.status} />
              <Badge value={incident.created_by} />
              <ReviewStateBadge value={incident.review_state} />
            </div>
            <h1 className="text-xl font-semibold tracking-tight break-all">
              Incident {incident.incident_id}
            </h1>
            <ObjectId value={incident.incident_id} />
            <p className="text-lg font-medium whitespace-pre-wrap break-words">{incident.title}</p>
            <p className="text-sm whitespace-pre-wrap break-words text-muted-foreground">
              요약: {incident.summary ?? '없음'}
            </p>
            <div className="grid gap-x-6 gap-y-1 border-t border-border pt-3 text-sm text-muted-foreground lg:grid-cols-3">
              <p className="break-words">
                전술: {incident.tactics.length ? incident.tactics.join(', ') : '없음'}
              </p>
              <p>
                처음: <Timestamp value={incident.first_seen} /> · 마지막:{' '}
                <Timestamp value={incident.last_seen} />
              </p>
              <p className="flex flex-wrap items-center gap-2">
                Case:{' '}
                {detail.case_id === null ? (
                  '없음'
                ) : (
                  <ObjectId
                    value={detail.case_id}
                    href={`/cases/${encodeURIComponent(detail.case_id)}`}
                  />
                )}
              </p>
            </div>
            <Extensions value={incident.extensions} />
          </header>
          <div className="mt-4 space-y-4">
            <IncidentMembers members={incident.members} />
            <IncidentReport artifact={detail.artifact} />
          </div>
          <div className="mt-4 grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,360px)]">
            <div className="min-w-0 space-y-4">
              <Section label="L2 검토 기록" description="회차는 코어가 정한 값입니다.">
                {!detail.reviews.length && <p className="text-sm text-muted-foreground">없음</p>}
                {detail.reviews.map((review, index) => (
                  <article
                    key={index}
                    className="min-w-0 space-y-1.5 rounded-md border border-border bg-muted p-3 text-sm"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-semibold break-all">{review.reviewer}</p>
                      <Badge value={review.decision} />
                      {review.reject_type === null ? (
                        <span className="text-xs text-muted-foreground">반려 유형 없음</span>
                      ) : (
                        <Badge value={review.reject_type} />
                      )}
                      <span className="text-xs font-semibold">{review.round}회차</span>
                      <span className="ml-auto text-xs text-faint-foreground">
                        <Timestamp value={review.created_at} />
                      </span>
                    </div>
                    <p className="whitespace-pre-wrap break-words">{review.comment ?? '없음'}</p>
                  </article>
                ))}
              </Section>
              <Section label="관련 티켓" description="묶음 항목 중 티켓과 그 Lookup">
                {detail.tickets.length ? (
                  <TicketList tickets={detail.tickets} />
                ) : (
                  <p className="text-sm text-muted-foreground">없음</p>
                )}
              </Section>
              <Section label="헌팅 결과" description="묶음 항목 중 L3 헌팅 결과">
                {!detail.hunts.length && <p className="text-sm text-muted-foreground">없음</p>}
                {detail.hunts.map((hunt) => (
                  <article
                    key={hunt.hunt_id}
                    className="min-w-0 space-y-2 rounded-md border border-border bg-muted p-3"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <ObjectId
                        value={hunt.hunt_id}
                        href={`/hunts/${encodeURIComponent(hunt.hunt_id)}`}
                      />
                      <Badge value={null} severity={hunt.severity_id} />
                      <ToneBadge tone={hunt.is_anomaly ? 'warning' : 'neutral'}>
                        {hunt.is_anomaly ? '이상 징후' : '이상 없음'}
                      </ToneBadge>
                      <span className="ml-auto text-xs text-faint-foreground">
                        <Timestamp value={hunt.created_at} />
                      </span>
                    </div>
                    <p className="whitespace-pre-wrap break-words">{hunt.hypothesis}</p>
                    <p className="text-xs break-words text-muted-foreground">
                      방법 {hunt.method} · 기법{' '}
                      {hunt.techniques.length ? hunt.techniques.join(', ') : '없음'}
                    </p>
                    <p className="font-mono text-xs whitespace-pre-wrap [overflow-wrap:anywhere]">
                      {hunt.query_summary}
                    </p>
                    <p className="text-xs break-words text-muted-foreground">
                      사람 확인 {hunt.needs_human ? '필요' : '불필요'} ·{' '}
                      {hunt.human_reason ?? '없음'}
                    </p>
                    <EvidenceList label={`헌팅 근거 ${hunt.hunt_id}`} evidence={hunt.evidence} />
                  </article>
                ))}
              </Section>
              <AgentLog steps={detail.steps} />
            </div>
            <aside className="min-w-0 lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto">
              <IncidentReview
                key={incident.incident_id}
                incident={incident}
                refreshFailed={query.isError}
              />
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
