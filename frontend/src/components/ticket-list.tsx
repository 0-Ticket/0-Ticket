import type { AssetInfo, Ticket } from '../contracts';
import { useAlert } from '../api/ticket-queries';
import { registeredLabel } from '../lib/display';
import { Badge, Extensions, ObjectId, QueryError, Timestamp } from './contract-display';

function Asset({ value }: { value: AssetInfo | null }) {
  if (!value) return <p>자산 정보 없음</p>;
  return (
    <div className="space-y-1">
      <p className="font-medium">{value.hostname}</p>
      <p>
        중요도 {value.criticality} · 담당자 {value.owner ?? '없음'} · 영역 {value.zone ?? '없음'}
      </p>
      <p>{value.shared ? '공용 자산' : '전용 자산'}</p>
      <Extensions value={value.extensions} />
    </div>
  );
}
function AlertLookup({ id }: { id: string }) {
  const query = useAlert(id);
  return (
    <section
      aria-label={`알럿 ${id}`}
      className="space-y-2 rounded border border-border p-3 text-sm"
    >
      <ObjectId value={id} />
      {query.isPending && <p role="status">알럿 불러오는 중…</p>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void query.refetch()}
        />
      )}
      {query.data && (
        <>
          <p>
            {query.data.rule_name} <Badge value={null} severity={query.data.severity_id} />
          </p>
          <div className="grid gap-3 lg:grid-cols-3">
            <div>
              <h4 className="mb-1 font-semibold">출발지 자산</h4>
              <Asset value={query.data.src_asset} />
            </div>
            <div>
              <h4 className="mb-1 font-semibold">목적지 자산</h4>
              <Asset value={query.data.dst_asset} />
            </div>
            <div>
              <h4 className="mb-1 font-semibold">계정</h4>
              {query.data.user_info ? (
                <>
                  <p>{query.data.user_info.user}</p>
                  <p>부서 {query.data.user_info.dept ?? '없음'}</p>
                  <p>{query.data.user_info.privileged ? '관리자 계정' : '일반 계정'}</p>
                  <Extensions value={query.data.user_info.extensions} />
                </>
              ) : (
                <p>없음</p>
              )}
            </div>
          </div>
          <Extensions value={query.data.extensions} />
        </>
      )}
    </section>
  );
}
export function TicketList({ tickets }: { tickets: Ticket[] }) {
  return (
    <ol className="space-y-4">
      {tickets.map((ticket) => (
        <li key={ticket.ticket_id} className="rounded-lg border border-border p-4">
          <article className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <ObjectId
                value={ticket.ticket_id}
                href={`/tickets/${encodeURIComponent(ticket.ticket_id)}`}
              />
              <div className="flex items-center gap-2">
                <span className="font-semibold">우선순위 {ticket.priority}</span>
                <Badge value={ticket.status} />
                <Badge value={ticket.verdict?.verdict ?? null} />
              </div>
            </div>
            <p className="text-sm">
              처리 유형 {registeredLabel(ticket.handling_type)} · 전문 에이전트{' '}
              {registeredLabel(ticket.specialist)}
            </p>
            <div className="flex flex-wrap gap-x-6 text-xs">
              <span>
                생성 <Timestamp value={ticket.created_at} />
              </span>
              <span>
                수정 <Timestamp value={ticket.updated_at} />
              </span>
            </div>
            <ul className="text-sm">
              {ticket.entities.map((entity, index) => (
                <li key={index}>
                  {registeredLabel(entity.type)}: {entity.value}
                </li>
              ))}
            </ul>
            {ticket.verdict && (
              <div className="rounded bg-accent p-3 text-sm">
                <p className="whitespace-pre-wrap break-words">{ticket.verdict.summary}</p>
                <p>확신도 {ticket.verdict.confidence}</p>
                <p>검토 사유: {ticket.verdict.human_reason ?? '없음'}</p>
                <ul>
                  {ticket.verdict.evidence.map((evidence, index) => (
                    <li key={index}>
                      {evidence.ref_type} · <ObjectId value={evidence.ref_id} />: {evidence.note}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <Extensions value={ticket.extensions} />
            <div className="space-y-2">
              {ticket.alert_ids.map((id) => (
                <AlertLookup key={id} id={id} />
              ))}
            </div>
          </article>
        </li>
      ))}
    </ol>
  );
}
