import { useState, type PropsWithChildren } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { config } from '../config';
import { ThemeProvider } from '../lib/theme';
import { ApiError } from '../api/client';

export function Providers({ children }: PropsWithChildren) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchInterval: config.pollIntervalMs,
            retry: (count, error) =>
              count < 1 && (!(error instanceof ApiError) || error.code === 'internal'),
          },
          mutations: { retry: false },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <ThemeProvider>{children}</ThemeProvider>
    </QueryClientProvider>
  );
}
