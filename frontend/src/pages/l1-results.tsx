import { useL1Decisions, useTickets } from '../api/ticket-queries';
import { QueryError, StatusNote } from '../components/contract-display';
import { DecisionList } from '../components/l1-records';
import { PageHeader } from '../components/page-header';
import { TicketList } from '../components/ticket-list';
import { Button } from '../components/ui/button';
import { Section } from '../components/ui/card';

// F1, box 27: read-only L1 results. There is no control that changes a decision;
// human approval exists only in box 21 (docs/architecture.md).
export function L1ResultsPage() {
  const decisions = useL1Decisions('alert');
  const tickets = useTickets(false);
  const rows = decisions.data?.pages.flatMap((page) => page.items) ?? [];
  const items = tickets.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="L1 RESULTS"
        title="L1 결과 조회"
        description={
          <>
            <p>정규화부터 L1 판정까지는 자동입니다. 승격·보류·판정 결과를 읽기만 합니다.</p>
            <p>알럿 ID를 선택하면 그 알럿의 L1 결과, 티켓 ID를 선택하면 티켓 상세로 갑니다.</p>
          </>
        }
      />
      <div className="space-y-4">
        <DecisionList
          decisions={rows}
          label="알럿 L1 결정"
          description="티켓이 되기 전 알럿의 승격·보류 기록"
          linkSubjects
          ready={!!decisions.data && !decisions.error}
          action={
            decisions.hasNextPage && (
              <Button
                variant="outline"
                size="sm"
                disabled={decisions.isFetching}
                onClick={() => void decisions.fetchNextPage()}
              >
                더 보기
              </Button>
            )
          }
        >
          {decisions.isPending && <StatusNote busy>알럿 결정 불러오는 중…</StatusNote>}
          {decisions.error && (
            <QueryError
              error={decisions.error}
              busy={decisions.isFetching}
              retry={() =>
                void (decisions.isFetchNextPageError
                  ? decisions.fetchNextPage()
                  : decisions.refetch())
              }
            />
          )}
        </DecisionList>
        <Section label="티켓 L1 결과" description="시나리오·L1 승격 티켓의 판정 결과">
          {tickets.isPending && <StatusNote busy>티켓 불러오는 중…</StatusNote>}
          {tickets.error && (
            <QueryError
              error={tickets.error}
              busy={tickets.isFetching}
              retry={() =>
                void (tickets.isFetchNextPageError ? tickets.fetchNextPage() : tickets.refetch())
              }
            />
          )}
          {tickets.data && (
            <>
              {!items.length && <StatusNote>티켓이 없습니다.</StatusNote>}
              <TicketList tickets={items} />
              {tickets.hasNextPage && (
                <Button
                  className="w-full"
                  variant="outline"
                  disabled={tickets.isFetching}
                  onClick={() => void tickets.fetchNextPage()}
                >
                  더 보기
                </Button>
              )}
            </>
          )}
        </Section>
      </div>
    </div>
  );
}
