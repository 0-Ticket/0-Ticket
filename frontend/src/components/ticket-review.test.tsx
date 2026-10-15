import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import { routes } from '../app/router';
import { ThemeProvider } from '../lib/theme';
import { server } from '../mocks/server';
import fixture from '../../../tests/fixtures/frontend/ticket-detail.json';

function mount(path = '/tickets/tk_sample') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return { client, router };
}
async function fill() {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText('검토자'), 'reviewer-demo');
  await user.click(screen.getByLabelText('FP'));
  await user.type(screen.getByLabelText(/검토 이유/), '검토 근거');
  return user;
}

it('blocks missing reviewer and reason and sends only the documented request fields', async () => {
  const bodies: unknown[] = [];
  server.use(
    http.post('*/api/tickets/:id/reviews', async ({ request }) => {
      bodies.push(await request.json());
      return HttpResponse.json({ ...fixture.reviews[0], reviewer: 'reviewer-demo' });
    }),
  );
  mount();
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: '검토 제출' }));
  expect(bodies).toEqual([]);
  await user.type(screen.getByLabelText('검토자'), 'reviewer-demo');
  await user.click(screen.getByLabelText('FP'));
  await user.click(screen.getByRole('button', { name: '검토 제출' }));
  expect(bodies).toEqual([]);
  await user.type(screen.getByLabelText(/검토 이유/), '   ');
  await user.click(screen.getByRole('button', { name: '검토 제출' }));
  expect(bodies).toEqual([]);
  await user.type(screen.getByLabelText(/검토 이유/), '확인');
  await user.click(screen.getByRole('button', { name: '검토 제출' }));
  await waitFor(() =>
    expect(bodies).toEqual([{ reviewer: 'reviewer-demo', decision: 'fp', reason: '확인' }]),
  );
});

it.each(['tp', 'fp'] as const)(
  'maps agreement with %s to the API enum without a reason',
  async (verdict) => {
    const value = structuredClone(fixture);
    value.ticket.verdict.verdict = verdict;
    let body: unknown;
    server.use(
      http.get('*/api/tickets/tk_sample', () => HttpResponse.json(value)),
      http.post('*/api/tickets/:id/reviews', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(fixture.reviews[0]);
      }),
    );
    mount();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('검토자'), 'demo');
    await user.click(screen.getByRole('button', { name: '동의' }));
    await user.click(screen.getByRole('button', { name: '검토 제출' }));
    await waitFor(() =>
      expect(body).toEqual({ reviewer: 'demo', decision: verdict, reason: null }),
    );
  },
);

it('prevents concurrent submissions and refetches server state across detail and both F1 lists', async () => {
  const { router } = mount('/review');
  const user = userEvent.setup();
  await screen.findByText('검토 대기 3건');
  await user.click(screen.getByRole('link', { name: '전체 티켓' }));
  await user.click(await screen.findByRole('link', { name: 'tk_sample' }));
  await fill();
  await user.dblClick(screen.getByRole('button', { name: '검토 제출' }));
  await screen.findByText('검토가 저장되었습니다.');
  expect(await screen.findByText('오탐 종결')).toBeInTheDocument();
  expect(screen.getByText('reviewer-demo')).toBeInTheDocument();
  await user.click(screen.getByRole('link', { name: '검토 대기함' }));
  await screen.findByText('검토 대기 2건');
  expect(screen.queryByRole('link', { name: 'tk_sample' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('link', { name: '전체 티켓' }));
  const link = await screen.findByRole('link', { name: 'tk_sample' });
  expect(within(link.closest('article')!).getByText('오탐 종결')).toBeInTheDocument();
  await act(() => router.navigate('/tickets/tk_sample'));
  expect(await screen.findByText('reviewer-demo')).toBeInTheDocument();
});

it.each([
  ['invalid_input', 400],
  ['not_found', 404],
  ['internal', 500],
  ['conflict', 409],
] as const)('shows %s without automatically retrying POST', async (code, status) => {
  let posts = 0,
    gets = 0;
  server.use(
    http.get('*/api/tickets/tk_sample', () => {
      gets++;
      return HttpResponse.json(fixture);
    }),
    http.post('*/api/tickets/:id/reviews', () => {
      posts++;
      return HttpResponse.json({ error: { code, message: `${code} <b>message</b>` } }, { status });
    }),
  );
  mount();
  const user = await fill();
  await user.click(screen.getByRole('button', { name: '검토 제출' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(`${code} <b>message</b>`);
  if (code === 'conflict') await waitFor(() => expect(gets).toBeGreaterThan(1));
  expect(posts).toBe(1);
  expect(document.querySelector('b')).toBeNull();
});

it('keeps a pending POST single and shows a server-selected status only after GET completes', async () => {
  const value = structuredClone(fixture);
  let posts = 0;
  let releasePost!: () => void;
  let releaseGet!: () => void;
  let refreshStarted = false;
  const postGate = new Promise<void>((resolve) => {
    releasePost = resolve;
  });
  const getGate = new Promise<void>((resolve) => {
    releaseGet = resolve;
  });
  server.use(
    http.get('*/api/tickets/tk_sample', async () => {
      if (posts) {
        refreshStarted = true;
        await getGate;
      }
      return HttpResponse.json(value);
    }),
    http.post('*/api/tickets/:id/reviews', async () => {
      posts++;
      await postGate;
      // Deliberately different from a client-side FP -> closed_fp assumption.
      value.ticket.status = 'closed_benign';
      return HttpResponse.json(fixture.reviews[0]);
    }),
  );
  mount();
  const user = await fill();
  await user.dblClick(screen.getByRole('button', { name: '검토 제출' }));
  await waitFor(() => expect(posts).toBe(1));
  expect(screen.getByRole('button', { name: '저장 중…' })).toBeDisabled();
  await act(async () => {
    releasePost();
  });
  await waitFor(() => expect(refreshStarted).toBe(true));
  expect(screen.queryByText('오탐 종결')).not.toBeInTheDocument();
  expect(screen.queryByText('정상 종결')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '저장 중…' })).toBeDisabled();
  await act(async () => {
    releaseGet();
  });
  expect(await screen.findByText('정상 종결')).toBeInTheDocument();
  expect(posts).toBe(1);
});

it('reports a failed refresh separately from a successful review and never sends it again', async () => {
  let saved = false,
    failRefresh = true,
    posts = 0;
  const value = structuredClone(fixture);
  server.use(
    http.get('*/api/tickets/tk_sample', () => {
      if (saved && failRefresh)
        return HttpResponse.json(
          { error: { code: 'internal', message: '상세 재조회 실패' } },
          { status: 500 },
        );
      return HttpResponse.json(value);
    }),
    http.post('*/api/tickets/:id/reviews', () => {
      posts++;
      saved = true;
      value.ticket.status = 'closed_fp';
      return HttpResponse.json(fixture.reviews[0]);
    }),
  );
  mount();
  const user = await fill();
  await user.click(screen.getByRole('button', { name: '검토 제출' }));
  await screen.findByText('검토가 저장되었습니다.');
  expect(await screen.findByRole('alert')).toHaveTextContent('상세 재조회 실패');
  expect(screen.getByRole('button', { name: '검토 제출' })).toBeDisabled();
  failRefresh = false;
  await user.click(screen.getByRole('button', { name: '다시 시도' }));
  await screen.findByText('오탐 종결');
  expect(posts).toBe(1);
});

it('refreshes a conflicting review to the latest server record', async () => {
  let conflict = false;
  const value = structuredClone(fixture);
  server.use(
    http.get('*/api/tickets/tk_sample', () => {
      if (conflict) {
        value.ticket.status = 'escalated';
        value.reviews[0].reviewer = 'other-reviewer';
      }
      return HttpResponse.json(value);
    }),
    http.post('*/api/tickets/:id/reviews', () => {
      conflict = true;
      return HttpResponse.json(
        { error: { code: 'conflict', message: '이미 처리됨' } },
        { status: 409 },
      );
    }),
  );
  mount();
  const user = await fill();
  await user.click(screen.getByRole('button', { name: '검토 제출' }));
  expect(await screen.findByText('other-reviewer')).toBeInTheDocument();
  expect(screen.getByText('상위 분석')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '검토 제출' })).toBeDisabled();
});
