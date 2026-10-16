import { useParams } from 'react-router';
import { useIncident } from '../api/incident-queries';
import { Badge, Extensions, ObjectId, QueryError, Timestamp } from '../components/contract-display';
import { EvidenceList } from '../components/evidence-list';
import { AgentLog } from '../components/agent-log';
import { IncidentMembers } from '../components/incident-members';
import { IncidentReport } from '../components/incident-report';
import { IncidentReview } from '../components/incident-review';
import { TicketList } from '../components/ticket-list';
import { HUMAN_HANDLING_LABEL } from '../lib/display';

export function IncidentDetailPage() {
  const { incident_id = '' } = useParams();
  const query = useIncident(incident_id);
  const detail = query.data;
  const incident = detail?.incident;
  // Documented display rule (box 21): two rejections are shown as human handling.
  const humanHandling =
    (detail?.reviews.filter((review) => review.decision === 'reject').length ?? 0) >= 2;
  return (
    <div className="mx-auto max-w-7xl space-y-6">
      {query.isPending && <p role="status">Incident 상세 불러오는 중…</p>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void query.refetch()}
        />
      )}
      {detail && incident && (
        <>
          <header className="space-y-2">
            <h1 className="text-2xl font-semibold break-all">Incident {incident.incident_id}</h1>
            <div className="flex flex-wrap items-center gap-3">
              <ObjectId value={incident.incident_id} />
              <Badge value={incident.status} />
              <Badge value={null} severity={incident.severity_id} />
              <Badge value={incident.created_by} />
              {humanHandling && (
                <span className="inline-block rounded border border-border bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-950 dark:bg-amber-950 dark:text-amber-100">
                  {HUMAN_HANDLING_LABEL}
                </span>
              )}
            </div>
            <p className="font-medium whitespace-pre-wrap break-words">{incident.title}</p>
            <p className="whitespace-pre-wrap break-words">요약: {incident.summary ?? '없음'}</p>
            <p>전술: {incident.tactics.length ? incident.tactics.join(', ') : '없음'}</p>
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
            <Extensions value={incident.extensions} />
          </header>
          <IncidentMembers members={incident.members} />
          <IncidentReport artifact={detail.artifact} />
          <IncidentReview
            key={incident.incident_id}
            incident={incident}
            caseId={detail.case_id}
            refreshFailed={query.isError}
          />
          <section aria-label="L2 검토 기록" className="space-y-3">
            <h2 className="text-lg font-semibold">L2 검토 기록</h2>
            {!detail.reviews.length && <p>없음</p>}
            {detail.reviews.map((review, index) => (
              <article key={index} className="space-y-2 rounded border border-border p-3">
                <p>{review.reviewer}</p>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge value={review.decision} />
                  {review.reject_type === null ? (
                    <span>반려 유형 없음</span>
                  ) : (
                    <Badge value={review.reject_type} />
                  )}
                  <span>{review.round}회차</span>
                </div>
                <p className="whitespace-pre-wrap break-words">{review.comment ?? '없음'}</p>
                <Timestamp value={review.created_at} />
              </article>
            ))}
          </section>
          <section aria-label="관련 티켓" className="space-y-3">
            <h2 className="text-lg font-semibold">관련 티켓</h2>
            {detail.tickets.length ? <TicketList tickets={detail.tickets} /> : <p>없음</p>}
          </section>
          <section aria-label="헌팅 결과" className="space-y-3">
            <h2 className="text-lg font-semibold">헌팅 결과</h2>
            {!detail.hunts.length && <p>없음</p>}
            {detail.hunts.map((hunt) => (
              <article key={hunt.hunt_id} className="space-y-2 rounded border border-border p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <ObjectId
                    value={hunt.hunt_id}
                    href={`/hunts/${encodeURIComponent(hunt.hunt_id)}`}
                  />
                  <Badge value={null} severity={hunt.severity_id} />
                  <span>{hunt.is_anomaly ? '이상 징후' : '이상 없음'}</span>
                </div>
                <p className="whitespace-pre-wrap break-words">{hunt.hypothesis}</p>
                <p className="text-sm">
                  방법 {hunt.method} · 기법{' '}
                  {hunt.techniques.length ? hunt.techniques.join(', ') : '없음'}
                </p>
                <p className="text-sm whitespace-pre-wrap break-words">{hunt.query_summary}</p>
                <p className="text-sm">
                  사람 확인 {hunt.needs_human ? '필요' : '불필요'} · {hunt.human_reason ?? '없음'}
                </p>
                <Timestamp value={hunt.created_at} />
                <EvidenceList label={`헌팅 근거 ${hunt.hunt_id}`} evidence={hunt.evidence} />
              </article>
            ))}
          </section>
          <AgentLog steps={detail.steps} />
        </>
      )}
    </div>
  );
}
