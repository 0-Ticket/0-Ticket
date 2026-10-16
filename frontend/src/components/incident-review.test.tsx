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
import fixture from '../../../tests/fixtures/frontend/incident-detail.json';

const PATH = '/incidents/in_web_campaign';
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

it('sends a rejection with reject_type and comment but never round', async () => {
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
      { reviewer: 'reviewer-demo', decision: 'approve', reject_type: null, comment: null },
    ]),
  );
  expect(bodies[0]).not.toHaveProperty('round');
});

it('submits once and refetches detail and list, showing the round chosen by the API', async () => {
  let listGets = 0;
  const listener = ({ request }: { request: Request }) => {
    if (new URL(request.url).pathname === '/api/incidents') listGets++;
  };
  server.events.on('request:start', listener);
  try {
    const { router } = mount('/incidents');
    const user = userEvent.setup({ delay: null });
    await user.click(await screen.findByRole('link', { name: 'in_manual' }));
    await screen.findByRole('heading', { name: 'Incident in_manual' });
    await fillReject();
    await user.dblClick(submit());
    await screen.findByText('검토가 저장되었습니다.');
    const reviews = within(screen.getByRole('region', { name: 'L2 검토 기록' }));
    expect(await reviews.findByText('reviewer-demo')).toBeInTheDocument();
    // The mock already holds rounds 1 and 2; the screen only shows the stored value.
    expect(reviews.getByText('3회차')).toBeInTheDocument();
    expect(reviews.getAllByText(/회차$/)).toHaveLength(3);
    // No client-side status or Case change: still the server's status.
    expect(screen.getByText('열림')).toBeInTheDocument();
    expect(screen.getByText('Case: 없음')).toBeInTheDocument();
    expect(submit()).toBeDisabled();
    const before = listGets;
    await act(() => router.navigate('/incidents'));
    await screen.findByRole('link', { name: 'in_manual' });
    await waitFor(() => expect(listGets).toBeGreaterThan(before));
  } finally {
    server.events.removeListener('request:start', listener);
  }
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
    mount();
    const user = await fillReject();
    await user.click(submit());
    expect(await screen.findByRole('alert')).toHaveTextContent(`${code} <b>message</b>`);
    if (code === 'conflict') await waitFor(() => expect(gets).toBeGreaterThan(1));
    else expect(submit()).toBeEnabled();
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
