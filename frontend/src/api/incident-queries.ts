import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './endpoints';
import { ApiError } from './client';
import type { IncidentReviewInput } from './types';

export function useIncidents() {
  return useInfiniteQuery({
    queryKey: ['incidents', {}],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => api.incidents({ cursor: pageParam }, signal),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}

export function useIncident(id: string) {
  return useQuery({
    queryKey: ['incident-detail', id],
    queryFn: ({ signal }) => api.incident(id, signal),
  });
}

// Status, round and Case creation come back from the API; nothing is written to the cache.
export function useIncidentReview(id: string) {
  const client = useQueryClient();
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ['incident-detail', id] }),
      client.invalidateQueries({ queryKey: ['incidents'] }),
      client.invalidateQueries({ queryKey: ['metrics'] }),
    ]);
  return useMutation({
    mutationFn: (body: IncidentReviewInput) => api.reviewIncident(id, body),
    retry: false,
    onSuccess: async () => {
      await refresh();
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.code === 'conflict') await refresh();
    },
  });
}
