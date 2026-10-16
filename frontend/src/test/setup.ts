import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { server } from '../mocks/server';
import { resetMockState } from '../mocks/handlers';
import { cleanupQueryClients } from './query-clients';

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(async () => {
  cleanup();
  await cleanupQueryClients();
  server.resetHandlers();
  resetMockState();
  localStorage.clear();
  document.documentElement.classList.remove('dark');
});
afterAll(() => server.close());
