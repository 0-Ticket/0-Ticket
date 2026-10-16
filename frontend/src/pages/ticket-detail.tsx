import { useParams } from 'react-router';
import { useTicket } from '../api/ticket-queries';
import {
  Badge,
  Extensions,
  ObjectId,
  QueryError,
  StatusNote,
  Timestamp,
} from '../components/contract-display';
import { Breadcrumbs } from '../components/page-header';
import { MetaLabel, Section } from '../components/ui/card';
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
    <div>
      {query.isPending && <StatusNote busy>티켓 상세 불러오는 중…</StatusNote>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void query.refetch()}
        />
      )}
      {detail && ticket && (
        <>
          <Breadcrumbs list="티켓 목록" to="/tickets" current={ticket.ticket_id} />
          <header className="min-w-0 space-y-3 rounded-lg border border-border bg-card p-4 shadow-card">
            <div className="flex flex-wrap items-center gap-2">
              <Badge value={ticket.status} />
              <span className="rounded bg-inset px-2 py-0.5 text-xs font-semibold">
                우선순위 {ticket.priority}
              </span>
            </div>
            <h1 className="text-xl font-semibold tracking-tight break-all">
              티켓 {ticket.ticket_id}
            </h1>
            <ObjectId value={ticket.ticket_id} />
            <div className="grid gap-x-6 gap-y-1 border-t border-border pt-3 text-sm text-muted-foreground lg:grid-cols-3">
              <p className="break-words">
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
            </div>
          </header>
          <div className="mt-4 grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,360px)]">
            <div className="min-w-0 space-y-4">
              <Section label="에이전트 판정" description="판정 결과와 그 근거">
                {verdict ? (
                  <>
                    <div className="flex flex-wrap items-center gap-3">
                      <Badge value={verdict.verdict} />
                      <span className="text-lg font-semibold tabular-nums">
                        확신도 {verdict.confidence}
                      </span>
                    </div>
                    <p className="whitespace-pre-wrap break-words">{verdict.summary}</p>
                    <p
                      className={
                        verdict.needs_human
                          ? 'rounded-md border border-warning/30 bg-warning-soft px-3 py-2 font-semibold break-words'
                          : 'text-sm break-words text-muted-foreground'
                      }
                    >
                      사람 검토 {verdict.needs_human ? '필요' : '불필요'} ·{' '}
                      {verdict.human_reason ?? '없음'}
                    </p>
                    <EvidenceList label="판정 근거" evidence={verdict.evidence} />
                    <div className="rounded-md border border-dashed border-border-strong p-3">
                      <MetaLabel>권고 조치</MetaLabel>
                      <p className="text-sm whitespace-pre-wrap break-words">
                        권고 · 실행하지 않음: {verdict.recommended_action}
                      </p>
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">없음</p>
                )}
              </Section>
              <Section label="전문 에이전트 결과" description="판정 근거 옆에 두는 전문 분석">
                {!detail.findings.length && <p className="text-sm text-muted-foreground">없음</p>}
                {detail.findings.map((finding, index) => (
                  <article
                    key={index}
                    className="min-w-0 space-y-3 rounded-md border border-border bg-muted p-3"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <h3 className="font-semibold break-all">
                        {registeredLabel(finding.specialist)}
                      </h3>
                      <span className="text-xs text-faint-foreground">
                        <Timestamp value={finding.created_at} />
                      </span>
                    </div>
                    <p className="text-sm break-words text-muted-foreground">{finding.question}</p>
                    <p className="whitespace-pre-wrap break-words">{finding.summary}</p>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      <p>
                        성공 여부: {finding.succeeded} · 확신도 {finding.confidence}
                      </p>
                      <p className="break-all">
                        {finding.attack_type === null
                          ? '없음'
                          : registeredLabel(finding.attack_type)}
                      </p>
                    </div>
                    <p
                      className={
                        finding.needs_human
                          ? 'rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm font-semibold break-words'
                          : 'text-xs break-words text-muted-foreground'
                      }
                    >
                      사람 검토 {finding.needs_human ? '필요' : '불필요'} ·{' '}
                      {finding.human_reason ?? '없음'}
                    </p>
                    <EvidenceList
                      label={`전문 분석 근거 ${index + 1}`}
                      evidence={finding.evidence}
                    />
                    <details className="rounded-md border border-border bg-card text-sm">
                      <summary className="cursor-pointer px-3 py-1.5 text-xs font-medium text-muted-foreground select-none">
                        전문 분석 상세
                      </summary>
                      <pre className="overflow-auto border-t border-border p-3 font-mono text-xs whitespace-pre-wrap [overflow-wrap:anywhere]">
                        {JSON.stringify(finding.details, null, 2)}
                      </pre>
                    </details>
                  </article>
                ))}
              </Section>
              <Section label="알럿 및 Lookup" description="알럿 필드와 자산·계정 조회 결과">
                {!detail.alerts.length && <p className="text-sm text-muted-foreground">없음</p>}
                {detail.alerts.map((alert) => (
                  <article
                    key={alert.alert_id}
                    className="min-w-0 space-y-3 rounded-md border border-border bg-muted p-3"
                  >
                    <div className="flex flex-wrap items-center gap-2">
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
              </Section>
              <Section label="엔티티와 확장 필드">
                {ticket.entities.length ? (
                  <ul className="flex min-w-0 flex-wrap gap-1.5 text-xs">
                    {ticket.entities.map((entity, index) => (
                      <li
                        key={index}
                        className="max-w-full rounded border border-border bg-inset px-2 py-0.5 font-mono break-all"
                      >
                        {registeredLabel(entity.type)}: {entity.value}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">없음</p>
                )}
                <Extensions value={ticket.extensions} />
              </Section>
              <AgentLog steps={detail.steps} />
              <Section label="검토 기록" description="이 티켓에 남은 L1 검토">
                {!detail.reviews.length && <p className="text-sm text-muted-foreground">없음</p>}
                {detail.reviews.map((review, index) => (
                  <article
                    key={index}
                    className="min-w-0 space-y-1.5 rounded-md border border-border bg-muted p-3 text-sm"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-semibold break-all">{review.reviewer}</p>
                      <Badge value={review.decision} />
                      <p className="text-xs text-muted-foreground">
                        {review.overturned ? '판정 변경' : '판정 동의'}
                      </p>
                      <span className="ml-auto text-xs text-faint-foreground">
                        <Timestamp value={review.created_at} />
                      </span>
                    </div>
                    <p className="whitespace-pre-wrap break-words">{review.reason ?? '없음'}</p>
                  </article>
                ))}
              </Section>
            </div>
            <aside className="min-w-0 space-y-4 lg:sticky lg:top-6">
              <TicketReview key={ticket.ticket_id} ticket={ticket} refreshFailed={query.isError} />
              <Section label="연결된 Incident">
                {detail.incident_ids.length ? (
                  <ul className="space-y-1">
                    {detail.incident_ids.map((id) => (
                      <li key={id}>
                        <ObjectId value={id} href={`/incidents/${encodeURIComponent(id)}`} />
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
