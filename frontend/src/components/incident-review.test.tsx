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
import { api } from '../api/endpoints';
import fixture from '../../../tests/fixtures/frontend/incident-detail.json';

const PATH = '/incidents/in_web_campaign';
const METRICS = ['metrics', 'current-waiting'];
const LIST = ['incidents', {}];
function mount(path = PATH) {
  const client = createTestQueryClient({
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
async function fillReject() {
  const user = userEvent.setup({ delay: null });
  await user.type(await screen.findByLabelText('검토자'), 'reviewer-demo');
  await user.click(screen.getByLabelText('반려'));
  await user.selectOptions(screen.getByLabelText(/반려 유형/), 'missing_step');
  await user.type(screen.getByLabelText(/검토 코멘트/), '조사 단계 보완');
  return user;
}
const submit = () => screen.getByRole('button', { name: '검토 제출' });
const reviewResponse = {
  ...fixture.l2_reviews[0],
  incident_id: 'in_web_campaign',
  round: 1,
};
function capture(bodies: unknown[]) {
  server.use(
    http.post('*/api/incidents/:id/reviews', async ({ request }) => {
      bodies.push(await request.json());
      return HttpResponse.json(reviewResponse);
    }),
  );
}

it('blocks submission without a reviewer or a decision', async () => {
  const bodies: unknown[] = [];
  capture(bodies);
  mount();
  const user = userEvent.setup({ delay: null });
  await screen.findByLabelText('검토자');
  await user.click(submit());
  await user.type(screen.getByLabelText('검토자'), 'reviewer-demo');
  await user.click(submit());
  expect(bodies).toEqual([]);
  expect(screen.getByRole('alert')).toHaveTextContent('검토자, 결정');
});

it.each([
  ['reject_type', null, '결론 재검토'],
  ['comment', 'wrong_conclusion', '   '],
])('blocks a rejection without %s', async (_, type, comment) => {
  const bodies: unknown[] = [];
  capture(bodies);
  mount();
  const user = userEvent.setup({ delay: null });
  await user.type(await screen.findByLabelText('검토자'), 'reviewer-demo');
  await user.click(screen.getByLabelText('반려'));
  if (type) await user.selectOptions(screen.getByLabelText(/반려 유형/), type);
  await user.type(screen.getByLabelText(/검토 코멘트/), comment);
  await user.click(submit());
  expect(bodies).toEqual([]);
  expect(screen.getByRole('alert')).toHaveTextContent('반려 유형과 코멘트');
});

it('sends a rejection echoing the received review_round but never round', async () => {
  const bodies: unknown[] = [];
  capture(bodies);
  mount();
  const user = await fillReject();
  await user.click(submit());
  await waitFor(() =>
    expect(bodies).toEqual([
      {
        reviewer: 'reviewer-demo',
        decision: 'reject',
        reject_type: 'missing_step',
        comment: '조사 단계 보완',
        expected_review_round: 1,
      },
    ]),
  );
  expect(bodies[0]).not.toHaveProperty('round');
});

it('approves without reject_type or comment', async () => {
  const bodies: unknown[] = [];
  capture(bodies);
  mount();
  const user = userEvent.setup({ delay: null });
  await user.type(await screen.findByLabelText('검토자'), 'reviewer-demo');
  await user.click(screen.getByLabelText('반려'));
  await user.selectOptions(screen.getByLabelText(/반려 유형/), 'wrong_grouping');
  await user.click(screen.getByLabelText('승인'));
  expect(screen.getByLabelText(/검토 코멘트/)).toBeInTheDocument();
  expect(screen.queryByLabelText(/반려 유형/)).not.toBeInTheDocument();
  await user.click(submit());
  await waitFor(() =>
    expect(bodies).toEqual([
      {
        reviewer: 'reviewer-demo',
        decision: 'approve',
        reject_type: null,
        comment: null,
        expected_review_round: 1,
      },
    ]),
  );
  expect(bodies[0]).not.toHaveProperty('round');
});

it('submits once and refetches detail, list and metrics, showing the round chosen by the API', async () => {
  let listGets = 0,
    posts = 0;
  const listener = ({ request }: { request: Request }) => {
    const path = new URL(request.url).pathname;
    if (path === '/api/incidents') listGets++;
    if (request.method === 'POST' && path === '/api/incidents/in_second_round/reviews') posts++;
  };
  server.events.on('request:start', listener);
  try {
    const { client, router } = mount('/incidents');
    client.setQueryData(METRICS, {});
    const user = userEvent.setup({ delay: null });
    await user.click(await screen.findByRole('link', { name: 'in_second_round' }));
    await screen.findByRole('heading', { name: 'Incident in_second_round' });
    expect(screen.getByText('L2 검토 대기')).toBeInTheDocument();
    await fillReject();
    await user.dblClick(submit());
    await screen.findByText('검토가 저장되었습니다.');
    const reviews = within(screen.getByRole('region', { name: 'L2 검토 기록' }));
    expect(await reviews.findByText('reviewer-demo')).toBeInTheDocument();
    // Round 2 was the opportunity the server opened; the screen only shows stored values.
    expect(reviews.getByText('2회차')).toBeInTheDocument();
    expect(reviews.getAllByText(/회차$/)).toHaveLength(2);
    // The second rejection moves only the review workflow; lifecycle status stays.
    expect(await screen.findByText('사람 직접 처리')).toBeInTheDocument();
    expect(screen.getByText('조사 중')).toBeInTheDocument();
    expect(screen.getByText('Case: 없음')).toBeInTheDocument();
    expect(submit()).toBeDisabled();
    expect(posts).toBe(1);
    expect(client.getQueryState(METRICS)?.isInvalidated).toBe(true);
    const before = listGets;
    await act(() => router.navigate('/incidents'));
    await screen.findByRole('link', { name: 'in_second_round' });
    await waitFor(() => expect(listGets).toBeGreaterThan(before));
  } finally {
    server.events.removeListener('request:start', listener);
  }
});

it('closes the form from the refetched review_state and reopens it only for a new opportunity', async () => {
  let posts = 0;
  const listener = ({ request }: { request: Request }) => {
    if (request.method === 'POST') posts++;
  };
  server.events.on('request:start', listener);
  try {
    const { client } = mount();
    const user = await fillReject();
    await user.click(submit());
    await screen.findByText('검토가 저장되었습니다.');
    expect(await screen.findByText(/L2 분석 중입니다/)).toBeInTheDocument();
    expect(submit()).toBeDisabled();
    expect(posts).toBe(1);
    // On the same mounted page, Box 19 finishing the reanalysis is represented by the server opening round 2.
    const [first] = (await api.incident('in_web_campaign')).reviews;
    server.use(
      http.get('*/api/incidents/in_web_campaign', () =>
        HttpResponse.json({
          incident: { ...fixture.incidents[0], review_state: 'awaiting_review', review_round: 2 },
          tickets: [],
          hunts: [],
          artifact: null,
          steps: [],
          reviews: [first],
          case_id: null,
        }),
      ),
    );
    const bodies: unknown[] = [];
    capture(bodies);
    await act(() => client.invalidateQueries({ queryKey: ['incident-detail', 'in_web_campaign'] }));
    await waitFor(() => expect(submit()).toBeEnabled());
    expect(screen.queryByText('검토가 저장되었습니다.')).not.toBeInTheDocument();
    expect(screen.getByLabelText('검토자')).toHaveValue('');
    await fillReject();
    await user.click(submit());
    await waitFor(() => expect(bodies).toMatchObject([{ expected_review_round: 2 }]));
  } finally {
    server.events.removeListener('request:start', listener);
  }
});

it('follows the server state on remount instead of a session flag', async () => {
  const { router } = mount();
  const user = await fillReject();
  await user.click(submit());
  expect(await screen.findByText(/L2 분석 중입니다/)).toBeInTheDocument();
  await act(() => router.navigate('/incidents'));
  await act(() => router.navigate(PATH));
  await screen.findByRole('heading', { name: 'Incident in_web_campaign' });
  expect(screen.getByText('L2 분석 중')).toBeInTheDocument();
  expect(submit()).toBeDisabled();
});

it('keeps the answered opportunity locked until the refetch returns', async () => {
  let release = () => {};
  let saved = false,
    posts = 0;
  const gate = new Promise<void>((resolve) => (release = resolve));
  server.use(
    http.get('*/api/incidents/in_web_campaign', async () => {
      if (saved) await gate;
      return undefined;
    }),
    http.post('*/api/incidents/:id/reviews', () => {
      posts++;
      saved = true;
      return HttpResponse.json(reviewResponse);
    }),
  );
  mount();
  const user = await fillReject();
  await user.click(submit());
  // POST succeeded but the refetch is still waiting: the form stays locked.
  await waitFor(() => expect(saved).toBe(true));
  expect(screen.getByRole('button', { name: '저장 중…' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: '저장 중…' }));
  expect(posts).toBe(1);
  release();
  await screen.findByText('검토가 저장되었습니다.');
  // The refetched detail still shows round 1 open (POST was stubbed), yet that answered
  // opportunity is not offered again.
  expect(screen.getByText('L2 검토 대기')).toBeInTheDocument();
  expect(submit()).toBeDisabled();
  expect(posts).toBe(1);
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
    http.post('*/api/incidents/:id/reviews', () => {
      posts++;
      return HttpResponse.json({ error: { code, message: `${code} <b>message</b>` } }, { status });
    }),
  );
  const listener = ({ request }: { request: Request }) => {
    if (
      request.method === 'GET' &&
      new URL(request.url).pathname === '/api/incidents/in_web_campaign'
    )
      gets++;
  };
  server.events.on('request:start', listener);
  try {
    const { client } = mount();
    client.setQueryData(METRICS, {});
    client.setQueryData(LIST, { pages: [], pageParams: [] });
    const user = await fillReject();
    await user.click(submit());
    expect(await screen.findByRole('alert')).toHaveTextContent(`${code} <b>message</b>`);
    const conflict = code === 'conflict';
    if (conflict) await waitFor(() => expect(gets).toBeGreaterThan(1));
    else expect(submit()).toBeEnabled();
    // Only a conflict refreshes server state; other errors leave the queries untouched.
    expect(client.getQueryState(METRICS)?.isInvalidated).toBe(conflict);
    expect(client.getQueryState(LIST)?.isInvalidated).toBe(conflict);
    if (!conflict) expect(gets).toBe(1);
    expect(posts).toBe(1);
    expect(document.querySelector('b')).toBeNull();
  } finally {
    server.events.removeListener('request:start', listener);
  }
});

it('reports a failed refresh separately from a saved review and never resends it', async () => {
  let saved = false,
    failRefresh = true,
    posts = 0;
  server.use(
    http.get('*/api/incidents/in_web_campaign', () => {
      if (saved && failRefresh)
        return HttpResponse.json(
          { error: { code: 'internal', message: '상세 재조회 실패' } },
          { status: 500 },
        );
      return undefined;
    }),
    http.post('*/api/incidents/:id/reviews', () => {
      posts++;
      saved = true;
      return HttpResponse.json(reviewResponse);
    }),
  );
  mount();
  const user = await fillReject();
  await user.click(submit());
  await screen.findByText('검토가 저장되었습니다.');
  expect(await screen.findByText('상세 재조회 실패')).toBeInTheDocument();
  expect(submit()).toBeDisabled();
  failRefresh = false;
  await user.click(screen.getByRole('button', { name: '다시 시도' }));
  await waitFor(() => expect(screen.queryByText('상세 재조회 실패')).not.toBeInTheDocument());
  expect(posts).toBe(1);
});
