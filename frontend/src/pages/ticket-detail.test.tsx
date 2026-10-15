import { createTestQueryClient } from '../test/query-clients';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import { routes } from '../app/router';
import { ThemeProvider } from '../lib/theme';
import { server } from '../mocks/server';
import fixture from '../../../tests/fixtures/frontend/ticket-detail.json';
import type { TicketDetail } from '../api/types';

function mount(path = '/tickets/tk_sample', interval: number | false = false) {
  const client = createTestQueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: interval },
      mutations: { retry: false },
    },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return { ...view, client, router };
}
function detail(data = structuredClone(fixture) as unknown as TicketDetail) {
  server.use(http.get('*/api/tickets/tk_sample', () => HttpResponse.json(data)));
  return data;
}

it('uses the detail envelope, orders steps, copies and expands only documented evidence types', async () => {
  detail();
  const requests: string[] = [];
  const listener = ({ request }: { request: Request }) =>
    requests.push(new URL(request.url).pathname);
  server.events.on('request:start', listener);
  try {
    const user = userEvent.setup();
    const { container } = mount();
    await screen.findByText('티켓 tk_sample', { selector: 'h1' });
    expect(screen.getByRole('heading', { name: '티켓 tk_sample' })).toBeVisible();
    expect(screen.getByText('example.attack')).toBeInTheDocument();
    expect(screen.getByText('sample-reviewer')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'in_sample' })).toHaveAttribute(
      'href',
      '/incidents/in_sample',
    );
    expect(screen.getAllByTestId('agent-step').map((x) => x.getAttribute('data-step'))).toEqual([
      '1',
      '2',
    ]);
    expect(screen.getByTitle(String(fixture.ticket.awaiting_human_at))).toHaveTextContent(
      new Date(fixture.ticket.awaiting_human_at).toLocaleString(),
    );
    expect(requests).toEqual(['/api/tickets/tk_sample']);
    const evidence = within(screen.getByRole('region', { name: '판정 근거' }));
    await user.click(evidence.getByRole('button', { name: 'custom_1 복사' }));
    expect(await navigator.clipboard.readText()).toBe('custom_1');
    expect(evidence.queryByRole('button', { name: 'custom_1 펼치기' })).not.toBeInTheDocument();
    for (const id of ['al_sample', 'ev_sample', 'raw_sample_1']) {
      await user.click(evidence.getByRole('button', { name: `${id} 펼치기` }));
    }
    await waitFor(() =>
      expect(requests).toEqual(
        expect.arrayContaining([
          '/api/alerts/al_sample',
          '/api/events/ev_sample',
          '/api/raw/raw_sample_1',
        ]),
      ),
    );
    expect(await screen.findByText('payload')).toBeInTheDocument();
    expect(container.querySelector('img, script, iframe, b')).toBeNull();
    expect(container.querySelector('a[href^="https:"]')).toBeNull();
    expect(screen.getByText(/권고 · 실행하지 않음/)).toBeInTheDocument();
  } finally {
    server.events.removeListener('request:start', listener);
  }
});

it('shows nulls and empty sections without inventing timestamps or incident links', async () => {
  const value = detail();
  value.ticket.verdict = null;
  value.ticket.awaiting_human_at = null;
  value.findings = [];
  value.steps = [];
  value.reviews = [];
  value.incident_ids = [];
  mount();
  await screen.findByText('티켓 tk_sample', { selector: 'h1' });
  expect(screen.getByRole('heading', { name: '티켓 tk_sample' })).toBeVisible();
  expect(screen.getByText('검토 대기 시작: 없음')).toBeInTheDocument();
  expect(screen.getAllByText('없음').length).toBeGreaterThan(0);
  expect(screen.queryByRole('button', { name: '동의' })).not.toBeInTheDocument();
  expect(screen.queryByRole('link', { name: /^in_/ })).not.toBeInTheDocument();
});

it('polls server detail and handles route changes and query errors', async () => {
  const value = detail();
  const { client, router, unmount } = mount('/tickets/tk_sample', 50);
  await screen.findByText('티켓 tk_sample', { selector: 'h1' });
  expect(screen.getByRole('heading', { name: '티켓 tk_sample' })).toBeVisible();
  value.ticket.status = 'closed_fp';
  await screen.findByText('오탐 종결');
  await act(() => router.navigate('/tickets/missing'));
  await screen.findByRole('alert');
  expect(screen.queryByRole('heading', { name: '티켓 tk_sample' })).not.toBeInTheDocument();
  unmount();
  client.clear();
});

it('renders malicious raw, LLM, extension and registered strings literally with retryable evidence errors', async () => {
  const value = detail();
  const malicious = '<img src=x onerror="alert(1)"> [url](https://example.com)';
  value.ticket.verdict!.summary = malicious;
  value.ticket.handling_type = 'example.handling';
  value.ticket.entities = [{ type: 'example.entity', value: malicious }];
  value.findings[0].details = { created_at: 'untrusted date', html: malicious };
  let failed = true;
  server.use(
    http.get('*/api/raw/raw_sample_1', () =>
      failed
        ? HttpResponse.json(
            { error: { code: 'internal', message: '근거 조회 실패' } },
            { status: 500 },
          )
        : HttpResponse.json({
            raw_id: 'raw_sample_1',
            source_type: 'example.source',
            received_at: 1791849600000,
            payload: malicious,
            sha256: 'synthetic',
          }),
    ),
  );
  const user = userEvent.setup();
  const { container } = mount();
  await screen.findByText('티켓 tk_sample', { selector: 'h1' });
  expect(screen.getByRole('heading', { name: '티켓 tk_sample' })).toBeVisible();
  const section = within(screen.getByRole('region', { name: '판정 근거' }));
  await user.click(section.getByRole('button', { name: 'raw_sample_1 펼치기' }));
  const error = await screen.findByRole('alert');
  expect(error).toHaveTextContent('근거 조회 실패');
  failed = false;
  await user.click(within(error).getByRole('button', { name: '다시 시도' }));
  await screen.findByText('payload');
  expect(screen.getAllByText(malicious).length).toBeGreaterThanOrEqual(2);
  await user.click(screen.getByText('전문 분석 상세'));
  expect(screen.getByText(/untrusted date/)).toBeVisible();
  expect(screen.getByText(/example.handling/)).toBeInTheDocument();
  expect(screen.getByText(/example.entity/)).toBeInTheDocument();
  for (const summary of screen.getAllByText(/입력·출력 발췌/)) await user.click(summary);
  expect(screen.getByText('<b>step two</b>')).toBeVisible();
  expect(container.querySelector('img, script, iframe, b, a[href^="https:"]')).toBeNull();
  await user.click(screen.getByRole('button', { name: '다크 모드' }));
  expect(document.documentElement).toHaveClass('dark');
  for (const time of container.querySelectorAll('time')) {
    expect(time).toHaveTextContent(new Date(Number(time.title)).toLocaleString());
  }
});

it('retries an initial detail error and preserves the awaiting timestamp after review state changes', async () => {
  let fail = true;
  const value = structuredClone(fixture);
  value.ticket.status = 'closed_fp';
  value.ticket.updated_at += 900000;
  server.use(
    http.get('*/api/tickets/tk_sample', () =>
      fail
        ? HttpResponse.json({ error: { code: 'internal', message: '상세 실패' } }, { status: 500 })
        : HttpResponse.json(value),
    ),
  );
  mount();
  expect(screen.getByText('티켓 상세 불러오는 중…')).toBeInTheDocument();
  await screen.findByText('상세 실패');
  fail = false;
  await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
  await screen.findByText('티켓 tk_sample', { selector: 'h1' });
  expect(screen.getByRole('heading', { name: '티켓 tk_sample' })).toBeVisible();
  expect(screen.getByTitle(String(fixture.ticket.awaiting_human_at))).toBeInTheDocument();
  expect(screen.queryByText(/소요 시간|경과 시간/)).not.toBeInTheDocument();
});
