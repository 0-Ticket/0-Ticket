import { useTickets, useWaitingCount } from '../api/ticket-queries';
import { QueryError, StatusNote } from '../components/contract-display';
import { Icon } from '../components/icon';
import { PageHeader } from '../components/page-header';
import { TicketList } from '../components/ticket-list';
import { Button } from '../components/ui/button';
import { MetaLabel } from '../components/ui/card';

function WaitingCount() {
  const query = useWaitingCount();
  return (
    <section
      aria-label="현재 검토 대기 건수"
      className="mb-5 flex flex-wrap items-center gap-4 rounded-lg border border-border bg-[linear-gradient(115deg,var(--card),color-mix(in_srgb,var(--warning-soft)_60%,var(--card)))] p-4 shadow-card"
    >
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-warning-soft text-warning">
        <Icon name="inbox" size={20} />
      </span>
      <div className="min-w-0 flex-1">
        <MetaLabel>지금 검토 필요</MetaLabel>
        {query.isPending && (
          <p role="status" className="text-muted-foreground">
            대기 건수 불러오는 중…
          </p>
        )}
        {query.error && (
          <QueryError
            error={query.error}
            busy={query.isFetching}
            retry={() => void query.refetch()}
          />
        )}
        {query.data?.available && (
          <p className="text-2xl font-semibold tracking-tight">
            검토 대기 {query.data.tickets_awaiting_human}건
          </p>
        )}
      </div>
    </section>
  );
}
export function TicketsPage({ review = false }: { review?: boolean }) {
  const query = useTickets(review);
  const tickets = query.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div>
      <PageHeader
        eyebrow={review ? 'HUMAN REVIEW QUEUE' : 'TICKET EXPLORER'}
        title={review ? '검토 대기함' : '전체 티켓'}
        description={
          <>
            <p>
              {review
                ? '에이전트 분석이 끝나 사람의 판단이 필요한 티켓입니다.'
                : '상태와 관계없이 모든 티켓을 조회합니다.'}
            </p>
            <p>우선순위가 높은 티켓부터 표시합니다. 티켓 ID를 선택하면 상세 화면으로 이동합니다.</p>
          </>
        }
      />
      {review && <WaitingCount />}
      <h2 className="mb-2 text-xs font-bold tracking-wider text-muted-foreground uppercase">
        {review ? '대기 중인 티켓' : '티켓 목록'}
      </h2>
      {query.isPending && <StatusNote busy>티켓 불러오는 중…</StatusNote>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void (query.isFetchNextPageError ? query.fetchNextPage() : query.refetch())}
        />
      )}
      {query.data && (
        <>
          {!tickets.length && <StatusNote>티켓이 없습니다.</StatusNote>}
          <TicketList tickets={tickets} emphasis={review} />
          {query.hasNextPage && (
            <Button
              className="mt-4 w-full"
              variant="outline"
              disabled={query.isFetching}
              onClick={() => void query.fetchNextPage()}
            >
              더 보기
            </Button>
          )}
        </>
      )}
      {query.isFetching && !query.isPending && <StatusNote busy>목록 갱신 중…</StatusNote>}
    </div>
  );
}
