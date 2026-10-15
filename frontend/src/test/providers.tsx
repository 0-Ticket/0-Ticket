import { useQueryClient } from '@tanstack/react-query';
import { useEffect, type PropsWithChildren } from 'react';
import { Providers } from '../app/providers';
import { trackQueryClient } from './query-clients';

function TrackQueries({ children }: PropsWithChildren) {
  const client = useQueryClient();
  useEffect(() => {
    trackQueryClient(client);
  }, [client]);
  return children;
}

// Exercise the production provider defaults while owning test teardown explicitly.
export function TestProviders({ children }: PropsWithChildren) {
  return (
    <Providers>
      <TrackQueries>{children}</TrackQueries>
    </Providers>
  );
}
