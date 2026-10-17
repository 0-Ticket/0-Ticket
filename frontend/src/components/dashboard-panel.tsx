import type { InfiniteData, UseInfiniteQueryResult } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import type { Page } from '../api/types';
import { QueryError, StatusNote } from './contract-display';
import { Icon } from './icon';
import { Button } from './ui/button';
import { MetaLabel, Section } from './ui/card';
import { TOP_ITEMS } from '../lib/dashboard';

export function EntryLink({ to, children }: { to: string; children: string }) {
  return (
    <Button asChild variant="outline" size="sm">
      <Link to={to}>
        {children}
        <Icon name="chevron" size={13} />
      </Link>
    </Button>
  );
}

export function CountTable({
  label,
  rows,
  render,
}: {
  label: string;
  rows: [string, number][];
  render: (value: string) => ReactNode;
}) {
  if (!rows.length) return <p className="text-xs text-muted-foreground">{label}: 없음</p>;
  return (
    <div className="min-w-0">
      <MetaLabel>{label}</MetaLabel>
      <table aria-label={label} className="w-full table-fixed text-left text-sm">
        <tbody>
          {rows.map(([value, count]) => (
            <tr key={value} className="border-b border-border last:border-0">
              <td className="min-w-0 py-1 pr-2 break-all">{render(value)}</td>
              <td className="w-20 py-1 text-right font-medium tabular-nums">{count}건</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TopList({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <MetaLabel>상단 항목 (API 순서, 최대 {TOP_ITEMS}건)</MetaLabel>
      <ul aria-label={label} className="divide-y divide-border rounded-md border border-border">
        {children}
      </ul>
    </div>
  );
}

export function ItemLink({ to, children }: { to: string; children: string }) {
  return (
    <Link
      className="min-w-0 font-mono text-[13px] font-medium break-all text-primary underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      to={to}
    >
      {children}
    </Link>
  );
}

// Shown with an error when older data is still on screen, so it is not read as current.
export function StaleNote() {
  return (
    <p className="text-xs text-warning">아래는 마지막으로 받은 값입니다. 갱신에 실패했습니다.</p>
  );
}

type ListQuery<T> = UseInfiniteQueryResult<InfiniteData<Page<T>>, Error>;

// One dashboard region over an existing list query. Loading, error, retry and empty states
// stay inside this region so one failing API never hides the others.
export function ListPanel<T>({
  label,
  actions,
  query,
  noun,
  empty,
  intro,
  children,
}: {
  label: string;
  actions: ReactNode;
  query: ListQuery<T>;
  noun: string;
  empty: string;
  intro?: ReactNode;
  children: (items: T[]) => ReactNode;
}) {
  const first = query.data?.pages[0];
  return (
    <Section
      label={label}
      action={<div className="flex flex-wrap gap-2">{actions}</div>}
      className="flex flex-col"
    >
      {intro}
      {query.isPending && <StatusNote busy>{`${noun} 불러오는 중…`}</StatusNote>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void query.refetch()}
        />
      )}
      {query.error && first && <StaleNote />}
      {first &&
        (first.items.length ? (
          <>
            <p className="text-xs text-muted-foreground">
              {`불러온 ${first.items.length}건 기준${first.next_cursor !== null ? ' · 더 있음' : ''}`}
            </p>
            {children(first.items)}
          </>
        ) : (
          <StatusNote>{empty}</StatusNote>
        ))}
    </Section>
  );
}
