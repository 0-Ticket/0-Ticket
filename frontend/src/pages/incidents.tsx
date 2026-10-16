import { useIncidents } from '../api/incident-queries';
import { QueryError } from '../components/contract-display';
import { IncidentList } from '../components/incident-list';
import { Button } from '../components/ui/button';

export function IncidentsPage() {
  const query = useIncidents();
  const incidents = query.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="mb-2 text-2xl font-semibold">Incident 목록</h1>
      <p className="mb-6 text-sm">
        Correlation이 묶은 Incident입니다. Incident ID를 선택하면 상세와 L2 검토로 이동합니다.
      </p>
      {query.isPending && <p role="status">Incident 불러오는 중…</p>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void (query.isFetchNextPageError ? query.fetchNextPage() : query.refetch())}
        />
      )}
      {query.data && (
        <>
          {!incidents.length && <p>Incident가 없습니다.</p>}
          <IncidentList incidents={incidents} />
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
