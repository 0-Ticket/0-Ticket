import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import { Providers } from '../app/providers';
import { routes } from '../app/router';
import { server } from '../mocks/server';
import { metrics } from '../mocks/data';

it('uses the current metrics count and requests only awaiting_human tickets without loading all pages', async () => {
  const requests: URL[] = [];
  server.use(
    http.get('*/api/tickets', ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json({ items: [], next_cursor: 'next' });
    }),
    http.get('*/api/metrics', ({ request }) => {
      const query = new URL(request.url).searchParams;
      expect(Number(query.get('to'))).toBeGreaterThan(Number(query.get('from')));
      return HttpResponse.json({ ...metrics, tickets_awaiting_human: 42 });
    }),
  );
  render(
    <Providers>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/review'] })} />
    </Providers>,
  );
  expect(await screen.findByText('검토 대기 42건')).toBeInTheDocument();
  expect(requests).toHaveLength(1);
  expect(requests[0].searchParams.get('status')).toBe('awaiting_human');
  expect(requests[0].searchParams.has('cursor')).toBe(false);
  expect(screen.queryByText(/대기 시간|생성 후 경과/)).not.toBeInTheDocument();
});

it('shows only awaiting_human tickets with the shared mock', async () => {
  render(
    <Providers>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/review'] })} />
    </Providers>,
  );
  expect(await screen.findAllByRole('link', { name: /^tk_/ })).toHaveLength(3);
  expect(screen.queryByRole('link', { name: 'tk_tie_a' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /동의|뒤집기/ })).not.toBeInTheDocument();
});
