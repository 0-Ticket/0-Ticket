import { useHunts } from '../api/hunt-queries';
import { QueryError, StatusNote } from '../components/contract-display';
import { HuntList } from '../components/hunt-list';
import { PageHeader } from '../components/page-header';
import { Button } from '../components/ui/button';

export function HuntsPage() {
  const query = useHunts();
  const hunts = query.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="HUNT"
        title="헌팅 결과"
        description={
          <p>
            L3가 알럿으로 올라오지 않은 이벤트를 조사한 결과입니다. 헌팅 ID를 선택하면 근거와 조사
            과정으로 이동합니다.
          </p>
        }
      />
      {query.isPending && <StatusNote busy>헌팅 결과 불러오는 중…</StatusNote>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void (query.isFetchNextPageError ? query.fetchNextPage() : query.refetch())}
        />
      )}
      {query.data && (
        <>
          {!hunts.length && <StatusNote>헌팅 결과가 없습니다.</StatusNote>}
          <HuntList hunts={hunts} />
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
