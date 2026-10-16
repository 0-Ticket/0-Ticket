import type { AssetInfo, Ticket } from '../contracts';
import { useAlert } from '../api/ticket-queries';
import { registeredLabel } from '../lib/display';
import { cn } from '../lib/utils';
import { Badge, Extensions, ObjectId, QueryError, Timestamp } from './contract-display';
import { Icon } from './icon';
import { ToneBadge } from './ui/badge';

const subheading = 'mb-1 text-[11px] font-semibold tracking-wider text-faint-foreground uppercase';

function Asset({ value }: { value: AssetInfo | null }) {
  if (!value) return <p className="text-muted-foreground">자산 정보 없음</p>;
  return (
    <div className="min-w-0 space-y-1">
      <p className="flex min-w-0 items-center gap-1.5 font-medium">
        <Icon name="server" size={14} className="text-faint-foreground" />
        <span className="min-w-0 break-all">{value.hostname}</span>
      </p>
      <p className="text-xs break-words text-muted-foreground">
        중요도 {value.criticality} · 담당자 {value.owner ?? '없음'} · 영역 {value.zone ?? '없음'}
      </p>
      {value.shared ? (
        <ToneBadge tone="warning">공용 자산</ToneBadge>
      ) : (
        <p className="text-xs text-muted-foreground">전용 자산</p>
      )}
      <Extensions value={value.extensions} />
    </div>
  );
}
function AlertLookup({ id }: { id: string }) {
  const query = useAlert(id);
  return (
    <section
      aria-label={`알럿 ${id}`}
      className="min-w-0 space-y-3 rounded-md border border-border bg-muted p-3 text-sm"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        <ObjectId value={id} />
        {query.data && (
          <p className="flex min-w-0 flex-wrap items-center gap-2 text-muted-foreground">
            <Icon name="alert" size={14} />
            {query.data.rule_name} <Badge value={null} severity={query.data.severity_id} />
          </p>
        )}
      </div>
      {query.isPending && (
        <p role="status" className="text-muted-foreground">
          알럿 불러오는 중…
        </p>
      )}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void query.refetch()}
        />
      )}
      {query.data && (
        <>
          <div className="grid min-w-0 gap-3 sm:grid-cols-3">
            <div className="min-w-0">
              <h4 className={subheading}>출발지 자산</h4>
              <Asset value={query.data.src_asset} />
            </div>
            <div className="min-w-0">
              <h4 className={subheading}>목적지 자산</h4>
              <Asset value={query.data.dst_asset} />
            </div>
            <div className="min-w-0">
              <h4 className={subheading}>계정</h4>
              {query.data.user_info ? (
                <div className="min-w-0 space-y-1">
                  <p className="flex min-w-0 items-center gap-1.5 font-medium">
                    <Icon name="user" size={14} className="text-faint-foreground" />
                    <span className="min-w-0 break-all">{query.data.user_info.user}</span>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    부서 {query.data.user_info.dept ?? '없음'}
                  </p>
                  {query.data.user_info.privileged ? (
                    <ToneBadge tone="warning">관리자 계정</ToneBadge>
                  ) : (
                    <p className="text-xs text-muted-foreground">일반 계정</p>
                  )}
                  <Extensions value={query.data.user_info.extensions} />
                </div>
              ) : (
                <p className="text-muted-foreground">없음</p>
              )}
            </div>
          </div>
          <Extensions value={query.data.extensions} />
        </>
      )}
    </section>
  );
}
// `emphasis` only changes presentation: the review queue puts the human-review reason first.
export function TicketList({
  tickets,
  emphasis = false,
}: {
  tickets: Ticket[];
  emphasis?: boolean;
}) {
  return (
    <ol className="space-y-3">
      {tickets.map((ticket) => (
        <li key={ticket.ticket_id}>
          <article
            className={cn(
              'min-w-0 overflow-hidden rounded-lg border border-border bg-card shadow-card',
              emphasis && 'border-l-4 border-l-warning',
            )}
          >
            <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border px-4 py-2.5">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <ObjectId
                  value={ticket.ticket_id}
                  href={`/tickets/${encodeURIComponent(ticket.ticket_id)}`}
                />
                <Badge value={ticket.status} />
                <Badge value={ticket.verdict?.verdict ?? null} />
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span className="rounded bg-inset px-2 py-0.5 font-semibold text-foreground">
                  우선순위 {ticket.priority}
                </span>
                <span>
                  생성 <Timestamp value={ticket.created_at} />
                </span>
                <span>
                  수정 <Timestamp value={ticket.updated_at} />
                </span>
              </div>
            </header>
            <div className="grid min-w-0 gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
              <div className="min-w-0 space-y-3">
                {ticket.verdict && (
                  <div className="min-w-0 space-y-2 text-sm">
                    <p
                      className={cn(
                        'break-words',
                        emphasis
                          ? 'rounded-md border border-warning/30 bg-warning-soft px-3 py-2 font-medium'
                          : 'text-muted-foreground',
                      )}
                    >
                      검토 사유: {ticket.verdict.human_reason ?? '없음'}
                    </p>
                    <p className="whitespace-pre-wrap break-words">{ticket.verdict.summary}</p>
                    <p className="text-xs text-muted-foreground">
                      확신도 {ticket.verdict.confidence}
                    </p>
                    <ol className="space-y-1">
                      {ticket.verdict.evidence.map((evidence, index) => (
                        <li
                          key={index}
                          className="flex min-w-0 items-start gap-2 text-xs text-muted-foreground"
                        >
                          <span
                            aria-hidden="true"
                            className="mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border border-border-strong text-[10px] text-faint-foreground"
                          >
                            {index + 1}
                          </span>
                          <span className="min-w-0 break-words">
                            {evidence.ref_type} · <ObjectId value={evidence.ref_id} />:{' '}
                            {evidence.note}
                          </span>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
                {ticket.entities.length > 0 && (
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
                )}
                <Extensions value={ticket.extensions} />
              </div>
              <div className="min-w-0 space-y-2">
                {ticket.alert_ids.map((id) => (
                  <AlertLookup key={id} id={id} />
                ))}
              </div>
            </div>
            <footer className="flex flex-wrap items-center gap-2 border-t border-border bg-muted px-4 py-2 text-xs text-muted-foreground">
              <Icon name="terminal" size={14} className="text-primary" />
              <p className="min-w-0 break-words">
                처리 유형 {registeredLabel(ticket.handling_type)} · 전문 에이전트{' '}
                {registeredLabel(ticket.specialist)}
              </p>
            </footer>
          </article>
        </li>
      ))}
    </ol>
  );
}
