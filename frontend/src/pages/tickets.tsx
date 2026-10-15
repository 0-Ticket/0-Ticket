import { useTickets, useWaitingCount } from '../api/ticket-queries';
import { QueryError } from '../components/contract-display';
import { TicketList } from '../components/ticket-list';
import { Button } from '../components/ui/button';

function WaitingCount() {
  const query = useWaitingCount();
  return (
    <section aria-label="현재 검토 대기 건수" className="mb-6 rounded-lg bg-accent p-4">
      {query.isPending && <p role="status">대기 건수 불러오는 중…</p>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void query.refetch()}
        />
      )}
      {query.data && (
        <p className="text-xl font-semibold">검토 대기 {query.data.tickets_awaiting_human}건</p>
      )}
    </section>
  );
}
export function TicketsPage({ review = false }: { review?: boolean }) {
  const query = useTickets(review);
  const tickets = query.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="mb-2 text-2xl font-semibold">{review ? '검토 대기함' : '전체 티켓'}</h1>
      <p className="mb-6 text-sm">
        우선순위가 높은 티켓부터 표시합니다. 티켓 ID를 선택하면 상세 화면으로 이동합니다.
      </p>
      {review && <WaitingCount />}
      {query.isPending && <p role="status">티켓 불러오는 중…</p>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void (query.isFetchNextPageError ? query.fetchNextPage() : query.refetch())}
        />
      )}
      {query.data && (
        <>
          {!tickets.length && <p>티켓이 없습니다.</p>}
          <TicketList tickets={tickets} />
          {query.hasNextPage && (
            <Button
              className="mt-4"
              variant="outline"
              disabled={query.isFetching}
              onClick={() => void query.fetchNextPage()}
            >
              더 보기
            </Button>
          )}
        </>
      )}
      {query.isFetching && !query.isPending && (
        <p role="status" className="mt-2 text-sm">
          목록 갱신 중…
        </p>
      )}
    </div>
  );
}
