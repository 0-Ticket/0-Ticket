import { useRules } from '../api/rule-queries';
import { QueryError, StatusNote } from '../components/contract-display';
import { PageHeader } from '../components/page-header';
import { RuleList } from '../components/rule-list';
import { Button } from '../components/ui/button';

// The list shows only references C18 carries; it never looks up hunts or Cases per row.
export function RulesPage() {
  const query = useRules();
  const rules = query.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="RULE"
        title="룰 제안"
        description={
          <p>
            헌팅 결과나 Case에서 나온 탐지 룰 제안입니다. 승인은 제안 상태만 바꾸며 SIEM에 반영하지
            않습니다.
          </p>
        }
      />
      {query.isPending && <StatusNote busy>룰 제안 불러오는 중…</StatusNote>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void (query.isFetchNextPageError ? query.fetchNextPage() : query.refetch())}
        />
      )}
      {query.data && (
        <>
          {!rules.length && <StatusNote>룰 제안이 없습니다.</StatusNote>}
          <RuleList rules={rules} />
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
