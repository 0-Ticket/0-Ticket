import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { api } from './endpoints';

export function useHunts() {
  return useInfiniteQuery({
    queryKey: ['hunts', {}],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => api.hunts({ cursor: pageParam }, signal),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}

export function useHunt(id: string) {
  return useQuery({
    queryKey: ['hunt-detail', id],
    queryFn: ({ signal }) => api.hunt(id, signal),
  });
}
