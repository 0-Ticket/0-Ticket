import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './endpoints';
import { ApiError } from './client';
import type { RuleReviewInput } from './types';

export function useRules() {
  return useInfiniteQuery({
    queryKey: ['rules', {}],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => api.rules({ cursor: pageParam }, signal),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}

export function useRule(id: string) {
  return useQuery({
    queryKey: ['rule-detail', id],
    queryFn: ({ signal }) => api.rule(id, signal),
  });
}

// The new C18 status comes back from the API and the refetch; nothing is written to the cache.
export function useRuleReview(id: string) {
  const client = useQueryClient();
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ['rule-detail', id] }),
      client.invalidateQueries({ queryKey: ['rules'] }),
    ]);
  return useMutation({
    mutationFn: (body: RuleReviewInput) => api.reviewRule(id, body),
    retry: false,
    onSuccess: async () => {
      await refresh();
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.code === 'conflict') await refresh();
    },
  });
}
