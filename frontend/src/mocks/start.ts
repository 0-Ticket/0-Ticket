import type { AppConfig } from '../config';

export async function startMocks(
  config: AppConfig,
  load: () => Promise<{
    worker: { start: (options: { onUnhandledFrame: 'bypass' }) => Promise<unknown> };
  }> = () => import('./browser'),
) {
  if (!config.useMock) return;
  const { worker } = await load();
  await worker.start({ onUnhandledFrame: 'bypass' });
}
