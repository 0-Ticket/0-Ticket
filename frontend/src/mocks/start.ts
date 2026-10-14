import type { AppConfig } from '../config';
import type { setupWorker } from 'msw/browser';

type WorkerStarter = Pick<ReturnType<typeof setupWorker>, 'start'>;

export async function startMocks(
  config: AppConfig,
  load: () => Promise<{ worker: WorkerStarter }> = () => import('./browser'),
) {
  if (!config.useMock) return;
  const { worker } = await load();
  await worker.start({ onUnhandledFrame: 'bypass' });
}
