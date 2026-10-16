import { useParams } from 'react-router';
import { useTicket } from '../api/ticket-queries';
import { Badge, Extensions, ObjectId, QueryError, Timestamp } from '../components/contract-display';
import { EvidenceList, ContractFields } from '../components/evidence-list';
import { AgentLog } from '../components/agent-log';
import { TicketReview } from '../components/ticket-review';
import { registeredLabel } from '../lib/display';

export function TicketDetailPage() {
  const { ticket_id = '' } = useParams();
  const query = useTicket(ticket_id);
  const detail = query.data;
  const ticket = detail?.ticket;
  const verdict = ticket?.verdict;
  return (
    <div className="mx-auto max-w-7xl space-y-6">
      {query.isPending && <p role="status">티켓 상세 불러오는 중…</p>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void query.refetch()}
        />
      )}
      {detail && ticket && (
        <>
          <header className="space-y-2">
            <h1 className="text-2xl font-semibold break-all">티켓 {ticket.ticket_id}</h1>
            <div className="flex flex-wrap items-center gap-3">
              <ObjectId value={ticket.ticket_id} />
              <Badge value={ticket.status} />
              <span>우선순위 {ticket.priority}</span>
            </div>
            <p>
              처리 유형: {registeredLabel(ticket.handling_type)} · 전문 에이전트:{' '}
              {registeredLabel(ticket.specialist)}
            </p>
            <p>
              검토 대기 시작:{' '}
              {ticket.awaiting_human_at === null ? (
                '없음'
              ) : (
                <Timestamp value={ticket.awaiting_human_at} />
              )}
            </p>
            <p>
              생성: <Timestamp value={ticket.created_at} /> · 수정:{' '}
              <Timestamp value={ticket.updated_at} />
            </p>
          </header>
          <div className="grid items-start gap-6 lg:grid-cols-2">
            <section
              aria-label="에이전트 판정"
              className="space-y-3 rounded border border-border p-4"
            >
              <h2 className="text-lg font-semibold">에이전트 판정</h2>
              {verdict ? (
                <>
                  <div className="flex gap-3">
                    <Badge value={verdict.verdict} />
                    <span>확신도 {verdict.confidence}</span>
                  </div>
                  <p className="whitespace-pre-wrap break-words">{verdict.summary}</p>
                  <p className={verdict.needs_human ? 'rounded bg-accent p-3 font-semibold' : ''}>
                    사람 검토 {verdict.needs_human ? '필요' : '불필요'} ·{' '}
                    {verdict.human_reason ?? '없음'}
                  </p>
                  <EvidenceList label="판정 근거" evidence={verdict.evidence} />
                  <p className="whitespace-pre-wrap break-words">
                    권고 · 실행하지 않음: {verdict.recommended_action}
                  </p>
                </>
              ) : (
                <p>없음</p>
              )}
            </section>
            <section
              aria-label="전문 에이전트 결과"
              className="space-y-3 rounded border border-border p-4"
            >
              <h2 className="text-lg font-semibold">전문 에이전트 결과</h2>
              {!detail.findings.length && <p>없음</p>}
              {detail.findings.map((finding, index) => (
                <article key={index} className="space-y-3 border-b border-border pb-4">
                  <h3 className="font-semibold">{registeredLabel(finding.specialist)}</h3>
                  <p>{finding.question}</p>
                  <p className="whitespace-pre-wrap break-words">{finding.summary}</p>
                  <p>
                    성공 여부: {finding.succeeded} · 확신도 {finding.confidence}
                  </p>
                  <p>
                    {finding.attack_type === null ? '없음' : registeredLabel(finding.attack_type)}
                  </p>
                  <p className={finding.needs_human ? 'font-semibold' : ''}>
                    사람 검토 {finding.needs_human ? '필요' : '불필요'} ·{' '}
                    {finding.human_reason ?? '없음'}
                  </p>
                  <Timestamp value={finding.created_at} />
                  <EvidenceList label={`전문 분석 근거 ${index + 1}`} evidence={finding.evidence} />
                  <details>
                    <summary className="cursor-pointer">전문 분석 상세</summary>
                    <pre className="whitespace-pre-wrap break-words">
                      {JSON.stringify(finding.details, null, 2)}
                    </pre>
                  </details>
                </article>
              ))}
            </section>
          </div>
          <TicketReview key={ticket.ticket_id} ticket={ticket} refreshFailed={query.isError} />
          <section aria-label="알럿 및 Lookup" className="space-y-3">
            <h2 className="text-lg font-semibold">알럿 및 Lookup</h2>
            {!detail.alerts.length && <p>없음</p>}
            {detail.alerts.map((alert) => (
              <article key={alert.alert_id} className="space-y-3 rounded border border-border p-4">
                <div className="flex flex-wrap gap-3">
                  <ObjectId value={alert.alert_id} />
                  <Badge value={null} severity={alert.severity_id} />
                </div>
                <ContractFields value={{ ...alert }} />
                <EvidenceList
                  label={`원본 연결 ${alert.alert_id}`}
                  evidence={alert.raw_ids.map((id) => ({
                    ref_type: 'raw',
                    ref_id: id,
                    note: '원본 로그',
                  }))}
                />
              </article>
            ))}
          </section>
          <section className="space-y-3">
            <h2 className="text-lg font-semibold">엔티티와 확장 필드</h2>
            {ticket.entities.length ? (
              <ul>
                {ticket.entities.map((entity, index) => (
                  <li key={index}>
                    {registeredLabel(entity.type)}: {entity.value}
                  </li>
                ))}
              </ul>
            ) : (
              <p>없음</p>
            )}
            <Extensions value={ticket.extensions} />
          </section>
          <AgentLog steps={detail.steps} />
          <section aria-label="검토 기록" className="space-y-3">
            <h2 className="text-lg font-semibold">검토 기록</h2>
            {!detail.reviews.length && <p>없음</p>}
            {detail.reviews.map((review, index) => (
              <article key={index} className="space-y-2 rounded border border-border p-3">
                <p>{review.reviewer}</p>
                <Badge value={review.decision} />
                <p>{review.overturned ? '판정 변경' : '판정 동의'}</p>
                <p className="whitespace-pre-wrap break-words">{review.reason ?? '없음'}</p>
                <Timestamp value={review.created_at} />
              </article>
            ))}
          </section>
          <section className="space-y-2">
            <h2 className="text-lg font-semibold">연결된 Incident</h2>
            {detail.incident_ids.length ? (
              <ul>
                {detail.incident_ids.map((id) => (
                  <li key={id}>
                    <ObjectId value={id} href={`/incidents/${encodeURIComponent(id)}`} />
                  </li>
                ))}
              </ul>
            ) : (
              <p>없음</p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
