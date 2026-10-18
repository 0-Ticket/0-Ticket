import { createTestQueryClient } from '../test/query-clients';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { delay, http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import { routes } from '../app/router';
import { ThemeProvider } from '../lib/theme';
import { server } from '../mocks/server';
import fixture from '../../../tests/fixtures/frontend/case-detail.json';

const CASE = fixture.cases[0];
const LIST = ['cases', {}];

function mount(path = '/cases/cs_web_breach') {
  const client = createTestQueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } },
  });
  client.setQueryData(LIST, { pages: [], pageParams: [] });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return { client };
}
const select = (index: number) => screen.getByLabelText(`작업 ${index} 상태`);
const rows = () => within(screen.getByRole('region', { name: '작업' })).getAllByTestId('case-task');
const badge = (row: HTMLElement) => row.querySelector('[data-tone]');
function countCaseGets() {
  const calls = { get: 0 };
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'GET' && new URL(request.url).pathname.endsWith('/cases/cs_web_breach'))
      calls.get += 1;
  });
  return calls;
}
function capture(bodies: unknown[], respond?: () => Response | Promise<Response>) {
  server.use(
    http.patch('*/api/cases/:id', async ({ request }) => {
      bodies.push(await request.clone().json());
      return respond ? respond() : undefined;
    }),
  );
}

it('shows each task with its owner, due time, status and null due as "없음"', async () => {
  mount();
  await screen.findByLabelText('작업 1 상태');
  const items = rows();
  expect(items).toHaveLength(3);
  expect(within(items[0]).getByText(CASE.tasks[0].task)).toBeInTheDocument();
  expect(badge(items[0])).toHaveTextContent('진행 중');
  expect(badge(items[1])).toHaveTextContent('할 일');
  expect(badge(items[2])).toHaveTextContent('완료');
  expect(within(items[1]).getByText(`담당: ${CASE.tasks[1].owner}`)).toBeInTheDocument();
  expect(within(items[1]).getByText('마감: 없음')).toBeInTheDocument();
  expect(
    within(items[0]).getByText(new Date(CASE.tasks[0].due_at!).toLocaleString()),
  ).toHaveAttribute('title', String(CASE.tasks[0].due_at));
  // Every contract status is offered; the screen does not enforce a transition order.
  for (const index of [1, 2, 3])
    expect(
      within(select(index))
        .getAllByRole('option')
        .map((o) => o.getAttribute('value')),
    ).toEqual(['todo', 'doing', 'done']);
});

it('patches the full tasks list with only the chosen status changed, then refetches', async () => {
  const bodies: unknown[] = [];
  capture(bodies);
  const calls = countCaseGets();
  const { client } = mount();
  const user = userEvent.setup();
  await screen.findByLabelText('작업 2 상태');
  const before = calls.get;
  // Skipping a step (todo → done) is the server's decision, not the screen's.
  await user.selectOptions(select(2), 'done');
  await screen.findByText('작업 상태가 저장되었습니다.');
  expect(bodies).toEqual([
    { tasks: CASE.tasks.map((task, i) => (i === 1 ? { ...task, status: 'done' } : task)) },
  ]);
  await waitFor(() => expect(calls.get).toBeGreaterThan(before));
  expect(badge(rows()[1])).toHaveTextContent('완료');
  expect(client.getQueryState(LIST)?.isInvalidated).toBe(true);
  server.events.removeAllListeners();
});

it('locks every task while a change is pending and never resubmits', async () => {
  const bodies: unknown[] = [];
  capture(bodies, async () => {
    await delay(150);
    return HttpResponse.json(
      { error: { code: 'internal', message: '저장 실패' } },
      { status: 500 },
    );
  });
  mount();
  const user = userEvent.setup();
  await screen.findByLabelText('작업 1 상태');
  await user.selectOptions(select(1), 'done');
  for (const index of [1, 2, 3]) expect(select(index)).toBeDisabled();
  await user.selectOptions(select(2), 'doing').catch(() => undefined);
  expect(await screen.findByRole('alert')).toHaveTextContent('저장 실패');
  await new Promise((resolve) => setTimeout(resolve, 200));
  expect(bodies).toHaveLength(1);
  // A failed write shows the server value again; nothing is written to the cache.
  expect(select(1)).toHaveValue('doing');
  expect(select(1)).toBeEnabled();
});

it.each([
  ['invalid_input', 400, '입력 오류'],
  ['conflict', 409, '충돌: 최신 Case를 다시 불러왔습니다.'],
  ['not_found', 404, 'Case를 찾을 수 없습니다.'],
  ['internal', 500, '서버 오류'],
])('shows %s from the API distinctly and sends once', async (code, status, prefix) => {
  const bodies: unknown[] = [];
  capture(bodies, () =>
    HttpResponse.json({ error: { code, message: `${code} message` } }, { status }),
  );
  mount();
  const user = userEvent.setup();
  await screen.findByLabelText('작업 1 상태');
  await user.selectOptions(select(1), 'todo');
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent(prefix);
  expect(alert).toHaveTextContent(`${code} message`);
  expect(screen.queryByText('작업 상태가 저장되었습니다.')).not.toBeInTheDocument();
  expect(bodies).toHaveLength(1);
});

it('keeps tasks locked until the refetch after a save settles', async () => {
  const bodies: unknown[] = [];
  capture(bodies);
  server.use(
    http.get('*/api/cases/:id', async () => {
      if (bodies.length) await delay(200);
      return undefined;
    }),
  );
  mount();
  const user = userEvent.setup();
  await screen.findByLabelText('작업 1 상태');
  await user.selectOptions(select(2), 'doing');
  await waitFor(() => expect(bodies).toHaveLength(1));
  // The PATCH has answered but the Case is still being refetched: no stale resend.
  expect(select(1)).toBeDisabled();
  await user.selectOptions(select(1), 'todo').catch(() => undefined);
  await screen.findByText('작업 상태가 저장되었습니다.');
  await waitFor(() => expect(select(1)).toBeEnabled());
  expect(bodies).toHaveLength(1);
  expect(badge(rows()[1])).toHaveTextContent('진행 중');
});

it('shows a task status outside the contract enum as received and resends it unchanged', async () => {
  const unknown = {
    ...CASE,
    tasks: CASE.tasks.map((task, i) => (i === 0 ? { ...task, status: 'example.blocked' } : task)),
  };
  server.use(
    http.get('*/api/cases/:id', () => HttpResponse.json({ case: unknown, proposal_ids: [] })),
  );
  const bodies: unknown[] = [];
  capture(bodies, () => HttpResponse.json(unknown));
  mount();
  const user = userEvent.setup();
  await screen.findByLabelText('작업 1 상태');
  expect(badge(rows()[0])).toHaveTextContent('example.blocked');
  expect(select(1)).toHaveValue('example.blocked');
  expect(within(select(1)).getByRole('option', { name: 'example.blocked' })).toBeDisabled();
  await user.selectOptions(select(2), 'doing');
  await screen.findByText('작업 상태가 저장되었습니다.');
  expect(bodies).toEqual([
    { tasks: unknown.tasks.map((task, i) => (i === 1 ? { ...task, status: 'doing' } : task)) },
  ]);
});

it('refetches the Case after a conflict', async () => {
  capture([], () =>
    HttpResponse.json({ error: { code: 'conflict', message: 'Case changed' } }, { status: 409 }),
  );
  const calls = countCaseGets();
  mount();
  const user = userEvent.setup();
  await screen.findByLabelText('작업 1 상태');
  const before = calls.get;
  await user.selectOptions(select(1), 'done');
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('충돌');
  expect(alert).toHaveTextContent('Case changed');
  await waitFor(() => expect(calls.get).toBeGreaterThan(before));
  server.events.removeAllListeners();
});

it('separates a saved change from a failed refetch and keeps tasks locked', async () => {
  let saved = false;
  capture([], () => {
    saved = true;
    return HttpResponse.json(CASE);
  });
  server.use(
    http.get('*/api/cases/:id', () =>
      saved
        ? HttpResponse.json({ error: { code: 'internal', message: 'GET 실패' } }, { status: 500 })
        : undefined,
    ),
  );
  mount();
  const user = userEvent.setup();
  await screen.findByLabelText('작업 1 상태');
  await user.selectOptions(select(1), 'done');
  expect(await screen.findByText('작업 상태가 저장되었습니다.')).toBeInTheDocument();
  expect(
    await screen.findByText('최신 Case를 조회하지 못했습니다. 상세 조회를 다시 시도하세요.'),
  ).toBeInTheDocument();
  expect(select(1)).toBeDisabled();
});
