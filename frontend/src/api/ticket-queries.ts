import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { api } from './endpoints';
import type { AlertRecord, EventRecord, L1DecisionRecord, RawRecord } from '../contracts';

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

export function useTicket(id: string) {
  return useQuery({
    queryKey: ['ticket-detail', id],
    queryFn: ({ signal }) => api.ticket(id, signal),
  });
}

// Only documented evidence routes are resolved. Registered unknown types remain text.
export function useEvidence(type: string, id: string, enabled: boolean) {
  return useQuery<AlertRecord | EventRecord | RawRecord>({
    queryKey: ['evidence', type, id],
    enabled: enabled && ['alert', 'event', 'raw'].includes(type),
    queryFn: ({ signal }) => {
      if (type === 'alert') return api.alert(id, signal);
      if (type === 'event') return api.event(id, signal);
      if (type === 'raw') return api.raw(id, signal);
      throw new Error('조회 API가 없는 근거 유형입니다.');
    },
  });
}

// The L1 result read reads C23 one page at a time; the screen never counts or reorders decisions.
export function useL1Decisions(subject_type: L1DecisionRecord['subject_type']) {
  return useInfiniteQuery({
    queryKey: ['l1-decisions', { subject_type }],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      api.l1Decisions({ cursor: pageParam, subject_type }, signal),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}

export function useAlertL1(id: string) {
  return useQuery({
    queryKey: ['alert-l1', id],
    queryFn: ({ signal }) => api.alertL1(id, signal),
  });
}
