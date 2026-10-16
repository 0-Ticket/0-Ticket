import { useIncidents } from '../api/incident-queries';
import { QueryError, StatusNote } from '../components/contract-display';
import { IncidentList } from '../components/incident-list';
import { PageHeader } from '../components/page-header';
import { Button } from '../components/ui/button';

export function IncidentsPage() {
  const query = useIncidents();
  const incidents = query.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="CORRELATION"
        title="Incident 목록"
        description={
          <p>
            Correlation이 묶은 Incident입니다. Incident ID를 선택하면 상세와 L2 검토로 이동합니다.
          </p>
        }
      />
      {query.isPending && <StatusNote busy>Incident 불러오는 중…</StatusNote>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void (query.isFetchNextPageError ? query.fetchNextPage() : query.refetch())}
        />
      )}
      {query.data && (
        <>
          {!incidents.length && <StatusNote>Incident가 없습니다.</StatusNote>}
          <IncidentList incidents={incidents} />
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
