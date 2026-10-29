import { QueryObserver } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { cleanupQueryClients, createTestQueryClient } from './query-clients';

it('cancels in-flight queries and clears query/mutation GC timers after unsubscribe', async () => {
  vi.useFakeTimers();
  try {
    const client = createTestQueryClient({
      defaultOptions: { queries: { retry: 1, refetchInterval: 100 } },
    });
    let signal: AbortSignal | undefined;
    const queryFn = vi.fn(({ signal: querySignal }: { signal: AbortSignal }) => {
      signal = querySignal;
      return new Promise<string>(() => {});
    });
    const observer = new QueryObserver(client, { queryKey: ['pending'], queryFn });
    const unsubscribe = observer.subscribe(() => {});
    expect(client.isFetching()).toBe(1);
    const mutation = client.getMutationCache().build(client, { mutationFn: async () => 'saved' });
    await mutation.execute(undefined);
    unsubscribe();
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    await cleanupQueryClients();
    expect(signal?.aborted).toBe(true);
    expect(client.isFetching()).toBe(0);
    expect(client.getQueryCache().getAll()).toEqual([]);
    expect(client.getMutationCache().getAll()).toEqual([]);
    await vi.runOnlyPendingTimersAsync();
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(300_000);
    expect(queryFn).toHaveBeenCalledTimes(1);
  } finally {
    await cleanupQueryClients();
    vi.useRealTimers();
  }
});
