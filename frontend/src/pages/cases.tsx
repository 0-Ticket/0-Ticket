import { useCases } from '../api/case-queries';
import { CaseList } from '../components/case-list';
import { QueryError, StatusNote } from '../components/contract-display';
import { PageHeader } from '../components/page-header';
import { Button } from '../components/ui/button';

export function CasesPage() {
  const query = useCases();
  const cases = query.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="CASE"
        title="Case 목록"
        description={
          <p>
            L2 승인 후 만들어진 Case입니다. Case ID를 선택하면 작업과 관련 Incident 보고서로
            이동합니다.
          </p>
        }
      />
      {query.isPending && <StatusNote busy>Case 불러오는 중…</StatusNote>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void (query.isFetchNextPageError ? query.fetchNextPage() : query.refetch())}
        />
      )}
      {query.data && (
        <>
          {!cases.length && <StatusNote>Case가 없습니다.</StatusNote>}
          <CaseList cases={cases} />
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
