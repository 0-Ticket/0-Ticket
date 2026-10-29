import { QueryClient, type QueryClientConfig } from '@tanstack/react-query';

const clients = new Set<QueryClient>();

export function trackQueryClient(client: QueryClient) {
  clients.add(client);
  return client;
}

export function createTestQueryClient(config: QueryClientConfig) {
  return trackQueryClient(new QueryClient(config));
}

// Call after React unmounts, before resetting MSW handlers and shared fixtures.
export async function cleanupQueryClients() {
  const current = [...clients];
  await Promise.all(current.map((client) => client.cancelQueries()));
  for (const client of current) client.clear();
  clients.clear();
}
