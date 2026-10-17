import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './endpoints';
import { ApiError } from './client';
import type { CaseTask } from '../contracts';

export function useCases() {
  return useInfiniteQuery({
    queryKey: ['cases', {}],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => api.cases({ cursor: pageParam }, signal),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}

export function useCase(id: string) {
  return useQuery({
    queryKey: ['case-detail', id],
    queryFn: ({ signal }) => api.case(id, signal),
  });
}

// The documented PATCH replaces the whole tasks list. The screen never decides allowed
// transitions or merges concurrent edits; it refetches and shows what the API returns.
export function useCaseTaskUpdate(id: string) {
  const client = useQueryClient();
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ['case-detail', id] }),
      client.invalidateQueries({ queryKey: ['cases'] }),
    ]);
  return useMutation({
    mutationFn: (tasks: CaseTask[]) => api.updateCase(id, { tasks }),
    retry: false,
    onSuccess: async () => {
      await refresh();
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.code === 'conflict') await refresh();
    },
  });
}
