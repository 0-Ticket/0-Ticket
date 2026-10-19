import { createTestQueryClient } from '../test/query-clients';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import { routes } from '../app/router';
import { ThemeProvider } from '../lib/theme';
import { server } from '../mocks/server';
import { data } from '../mocks/data';
import type { L1DecisionRecord } from '../contracts';
import untrusted from '../../../tests/fixtures/frontend/untrusted-text.json';

function mount(path = '/review') {
  const client = createTestQueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 1000 } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return { ...view, client };
}

const decisions = (subject_type: L1DecisionRecord['subject_type']) =>
  data.decisions.filter((item) => item.subject_type === subject_type);

it('reads alert decisions and tickets without any write control or metrics call', async () => {
  const requests: string[] = [];
  const listener = ({ request }: { request: Request }) => {
    const url = new URL(request.url);
    requests.push(`${request.method} ${url.pathname}${url.search}`);
  };
  server.events.on('request:start', listener);
  try {
    const { container } = mount();
    // First MSW -> Query -> render of this page exceeded the 1s default under heavy CPU load.
    await screen.findAllByRole('link', { name: 'al_held' }, { timeout: 3000 });
    expect(screen.getByRole('heading', { level: 1, name: 'L1 결과 조회' })).toBeVisible();
    const list = within(screen.getByRole('region', { name: '알럿 L1 결정' }));
    // Promotions, holds and every hold reason are told apart, newest first.
    expect(list.getAllByRole('listitem')).toHaveLength(decisions('alert').length);
    expect(list.getAllByText('보류').length).toBe(3);
    expect(list.getByText('L1 승격')).toBeInTheDocument();
    for (const reason of ['확신도 미만', 'LLM 실패', '증거 요청 실패'])
      expect(list.getByText(reason)).toBeInTheDocument();
    // al_held was held twice, so it owns two rows; both lead to its own L1 result.
    for (const link of list.getAllByRole('link', { name: 'al_held' }))
      expect(link).toHaveAttribute('href', '/alerts/al_held');
    // Ticket verdicts and their L1 decisions stay on the same screen.
    const tickets = within(screen.getByRole('region', { name: '티켓 L1 결과' }));
    expect(tickets.getByRole('link', { name: 'tk_scenario_l2' })).toHaveAttribute(
      'href',
      '/tickets/tk_scenario_l2',
    );
    expect(tickets.getByText('L2 승격')).toBeInTheDocument();
    expect(tickets.getAllByText('보류').length).toBeGreaterThan(0);
    // The alert of a listed ticket leads to its own L1 detail.
    expect(tickets.getByRole('link', { name: 'al_scenario' })).toHaveAttribute(
      'href',
      '/alerts/al_scenario',
    );
    await waitFor(() => expect(requests.length).toBeGreaterThan(1));
    expect(
      requests.every((request) =>
        /^GET \/api\/(l1\/decisions\?|tickets(\?|$)|alerts\/[^/?]+$)/.test(request),
      ),
    ).toBe(true);
    expect(requests.some((request) => request.includes('subject_type=alert'))).toBe(true);
    expect(requests.some((request) => request.includes('/api/metrics'))).toBe(false);
    expect(screen.queryByText(/검토 대기 \d+건/)).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /동의|뒤집기|승인|반려/ })).not.toBeInTheDocument();
    expect(container.querySelector('form')).toBeNull();
  } finally {
    server.events.removeListener('request:start', listener);
  }
});

it('continues the decision list past the default page without dropping or repeating rows', async () => {
  const page = (from: number, count: number): L1DecisionRecord[] =>
    Array.from({ length: count }, (_, index) => ({
      decision_id: `ld_page_${from + index}`,
      subject_type: 'alert',
      subject_id: 'al_held',
      decision: 'held',
      confidence: null,
      reason: 'below_threshold',
      created_at: 1791936000000 - (from + index),
    }));
  const queries: string[] = [];
  server.use(
    http.get('*/api/l1/decisions', ({ request }) => {
      const query = new URL(request.url).searchParams;
      queries.push(query.get('cursor') ?? 'first');
      return HttpResponse.json(
        query.get('cursor') === '50'
          ? { items: page(50, 7), next_cursor: null }
          : { items: page(0, 50), next_cursor: '50' },
      );
    }),
  );
  mount();
  const list = within(
    await screen.findByRole('region', { name: '알럿 L1 결정' }, { timeout: 3000 }),
  );
  await waitFor(() => expect(list.getAllByRole('listitem')).toHaveLength(50));
  await userEvent.click(list.getByRole('button', { name: '더 보기' }));
  await waitFor(() => expect(list.getAllByRole('listitem')).toHaveLength(57));
  const ids = list.getAllByRole('listitem').map((row) => row.getAttribute('data-decision-id'));
  expect(new Set(ids).size).toBe(57);
  expect(ids[0]).toBe('ld_page_0');
  expect(ids[56]).toBe('ld_page_56');
  expect(queries).toEqual(['first', '50']);
  expect(list.queryByRole('button', { name: '더 보기' })).not.toBeInTheDocument();
});

it('shows attacker and LLM strings as text and keeps empty lists readable', async () => {
  const ticket = structuredClone(data.tickets[0]);
  ticket.verdict!.summary = untrusted.summary;
  ticket.extensions = { ...untrusted.extensions };
  server.use(
    http.get('*/api/l1/decisions', () => HttpResponse.json({ items: [], next_cursor: null })),
    http.get('*/api/tickets', () => HttpResponse.json({ items: [ticket], next_cursor: null })),
  );
  const { container } = mount();
  await screen.findByText(untrusted.summary, undefined, { timeout: 3000 });
  expect(screen.getByText('알럿 L1 결정이 없습니다.')).toBeInTheDocument();
  expect(screen.getByText(untrusted.extensions['example.note'])).toBeInTheDocument();
  expect(container.querySelector('img, script, iframe, b')).toBeNull();
  expect(container.querySelector('a[href^="https:"]')).toBeNull();
});

it('retries a failed decision list without hiding the ticket list', async () => {
  let failed = true;
  server.use(
    http.get('*/api/l1/decisions', () =>
      failed
        ? HttpResponse.json(
            { error: { code: 'internal', message: '결정 조회 실패' } },
            { status: 500 },
          )
        : HttpResponse.json({ items: decisions('alert'), next_cursor: null }),
    ),
  );
  mount();
  const error = await screen.findByRole('alert', undefined, { timeout: 3000 });
  expect(error).toHaveTextContent('결정 조회 실패');
  expect(await screen.findByRole('link', { name: 'tk_scenario_l2' })).toBeInTheDocument();
  failed = false;
  await userEvent.click(within(error).getByRole('button', { name: '다시 시도' }));
  expect(await screen.findAllByRole('link', { name: 'al_held' })).toHaveLength(2);
});
