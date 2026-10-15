import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { api } from './endpoints';

export function useTickets(review: boolean) {
  return useInfiniteQuery({
    queryKey: ['tickets', { status: review ? 'awaiting_human' : null }],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      api.tickets(
        { cursor: pageParam, ...(review ? { status: 'awaiting_human' as const } : {}) },
        signal,
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}

export function useAlert(id: string) {
  return useQuery({
    queryKey: ['alerts', id],
    queryFn: ({ signal }) => api.alert(id, signal),
    staleTime: 30_000,
  });
}

export function useWaitingCount() {
  return useQuery({
    queryKey: ['metrics', 'current-waiting'],
    queryFn: ({ signal }) => {
      const now = new Date();
      const start = new Date(now);
      start.setHours(0, 0, 0, 0);
      return api.metrics({ from: start.getTime(), to: now.getTime() }, signal);
    },
  });
}
