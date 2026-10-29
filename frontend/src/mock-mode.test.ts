import { expect, it, vi } from 'vitest';
import { readConfig } from './config';
import { startMocks } from './mocks/start';
import type { setupWorker } from 'msw/browser';

it('switches interception with one environment variable and defaults off in production', async () => {
  const start = vi.fn<ReturnType<typeof setupWorker>['start']>().mockResolvedValue(undefined);
  const load = vi.fn(async () => ({ worker: { start } }));
  await startMocks(readConfig({ DEV: true, VITE_USE_MOCK: 'false' }), load);
  expect(load).not.toHaveBeenCalled();
  await startMocks(readConfig({ DEV: false }), load);
  expect(load).not.toHaveBeenCalled();
  await startMocks(readConfig({ DEV: true, VITE_USE_MOCK: 'true' }), load);
  expect(start).toHaveBeenCalledOnce();
  expect(start).toHaveBeenCalledWith({ onUnhandledFrame: 'bypass' });
  expect(readConfig({ DEV: true }).useMock).toBe(true);
});

it('documents defaults and rejects mistyped settings', () => {
  expect(readConfig({})).toEqual({ useMock: false, apiBaseUrl: '/api', pollIntervalMs: 30_000 });
  expect(
    readConfig({ VITE_API_BASE_URL: 'https://example.com/api', VITE_POLL_INTERVAL_MS: '5000' }),
  ).toMatchObject({ apiBaseUrl: 'https://example.com/api', pollIntervalMs: 5000 });
  expect(() => readConfig({ VITE_USE_MOCK: 'yes' })).toThrow();
  expect(() => readConfig({ VITE_POLL_INTERVAL_MS: '0' })).toThrow();
});
