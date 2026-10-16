import { render, screen, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import userEvent from '@testing-library/user-event';
import { TestProviders as Providers } from '../test/providers';
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
  // First MSW -> Query -> render of this page exceeded the 1s default under heavy CPU load.
  expect(
    await screen.findByText('검토 대기 42건', undefined, { timeout: 3000 }),
  ).toBeInTheDocument();
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
  // First MSW -> Query -> render of this page exceeded the 1s default under heavy CPU load.
  expect(await screen.findAllByRole('link', { name: /^tk_/ }, { timeout: 3000 })).toHaveLength(3);
  expect(screen.queryByRole('link', { name: 'tk_tie_a' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /동의|뒤집기/ })).not.toBeInTheDocument();
});

it('retries a metrics error and displays zero as the current waiting count', async () => {
  server.use(
    http.get('*/api/metrics', () =>
      HttpResponse.json(
        { error: { code: 'invalid_input', message: '지표 조회 실패' } },
        { status: 400 },
      ),
    ),
  );
  render(
    <Providers>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/review'] })} />
    </Providers>,
  );
  const error = await screen.findByRole('alert');
  expect(error).toHaveTextContent('지표 조회 실패');
  expect(screen.queryByText(/검토 대기 \d+건/)).not.toBeInTheDocument();
  server.use(
    http.get('*/api/metrics', () => HttpResponse.json({ ...metrics, tickets_awaiting_human: 0 })),
  );
  await userEvent.click(within(error).getByRole('button', { name: '다시 시도' }));
  expect(await screen.findByText('검토 대기 0건')).toBeInTheDocument();
});
