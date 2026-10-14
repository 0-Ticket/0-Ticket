type Environment = {
  DEV?: boolean;
  VITE_USE_MOCK?: string;
  VITE_API_BASE_URL?: string;
  VITE_POLL_INTERVAL_MS?: string;
};

export function readConfig(env: Environment) {
  const mock = env.VITE_USE_MOCK?.trim();
  if (mock && mock !== 'true' && mock !== 'false') {
    throw new Error('VITE_USE_MOCK must be true or false');
  }
  const pollIntervalMs = Number(env.VITE_POLL_INTERVAL_MS?.trim() || 30_000);
  if (!Number.isSafeInteger(pollIntervalMs) || pollIntervalMs < 1) {
    throw new Error('VITE_POLL_INTERVAL_MS must be a positive integer');
  }
  return {
    // Development works without .env; production requires explicit mock opt-in.
    useMock: mock ? mock === 'true' : env.DEV === true,
    apiBaseUrl: env.VITE_API_BASE_URL?.trim() || '/api',
    pollIntervalMs,
  };
}

export type AppConfig = ReturnType<typeof readConfig>;
export const config = readConfig(import.meta.env);
