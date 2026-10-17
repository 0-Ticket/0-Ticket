import { createTestQueryClient } from '../test/query-clients';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { delay, http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import { routes } from '../app/router';
import { ThemeProvider } from '../lib/theme';
import { server } from '../mocks/server';
import fixture from '../../../tests/fixtures/frontend/hunt-rule-detail.json';

const WEB = fixture.rules[0];
const LIST = ['rules', {}];

function mount(path = '/rules/rp_web_shell') {
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
const submit = () => screen.getByRole('button', { name: '검토 제출' });
function capture(bodies: unknown[], respond?: () => Response | Promise<Response>) {
  server.use(
    http.post('*/api/rules/:id/reviews', async ({ request }) => {
      bodies.push(await request.clone().json());
      return respond ? respond() : undefined;
    }),
  );
}
function countRuleGets() {
  const calls = { get: 0 };
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'GET' && new URL(request.url).pathname.endsWith('/rules/rp_web_shell'))
      calls.get += 1;
  });
  return calls;
}
async function fill(decision: '승인' | '반려', reviewer = 'reviewer-demo') {
  const user = userEvent.setup({ delay: null });
  await user.type(await screen.findByLabelText('검토자'), reviewer);
  await user.click(screen.getByLabelText(decision));
  return user;
}

it('blocks submission without a reviewer or a decision', async () => {
  const bodies: unknown[] = [];
  capture(bodies);
  mount();
  const user = userEvent.setup({ delay: null });
  await screen.findByLabelText('검토자');
  await user.click(submit());
  await user.type(screen.getByLabelText('검토자'), '   ');
  await user.click(screen.getByLabelText('승인'));
  await user.click(submit());
  expect(bodies).toEqual([]);
  expect(screen.getByRole('alert')).toHaveTextContent('검토자와 결정');
});

it.each([
  ['승인', 'approve', '승인됨'],
  ['반려', 'reject', '반려됨'],
] as const)(
  'sends only reviewer and decision for %s, then shows the refetched status',
  async (label, decision, shown) => {
    const bodies: unknown[] = [];
    capture(bodies);
    const { client } = mount();
    const user = await fill(label, '  reviewer-demo  ');
    await user.click(submit());
    await screen.findByText(/검토가 저장되었습니다/);
    expect(bodies).toEqual([{ reviewer: 'reviewer-demo', decision }]);
    // The list query is invalidated (refetched when shown) and the detail shows the refetch.
    expect(client.getQueryState(LIST)?.isInvalidated).toBe(true);
    expect((await screen.findAllByText(shown)).length).toBeGreaterThan(0);
    expect(screen.getByText('검토자: reviewer-demo')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '검토 제출' })).toBeNull();
  },
);

it('shows the server status even when it differs from the chosen decision', async () => {
  // The screen never maps approve → approved itself; it shows what the API returns.
  const returned = { ...WEB, status: 'example.queued', reviewer: 'reviewer-demo' };
  capture([], () => HttpResponse.json(returned));
  mount();
  const user = await fill('승인');
  await user.click(submit());
  const saved = await screen.findByText(/검토가 저장되었습니다/);
  expect(saved).toHaveTextContent('example.queued');
});

it('submits once on a double click and never retries a failed POST', async () => {
  const bodies: unknown[] = [];
  capture(bodies, async () => {
    await delay(100);
    return HttpResponse.json(
      { error: { code: 'internal', message: '저장 실패' } },
      { status: 500 },
    );
  });
  mount();
  const user = await fill('승인');
  const button = submit();
  await user.dblClick(button);
  await user.click(button).catch(() => undefined);
  expect(await screen.findByRole('alert')).toHaveTextContent('저장 실패');
  await new Promise((resolve) => setTimeout(resolve, 150));
  expect(bodies).toHaveLength(1);
});

it('refetches the rule and list after a conflict', async () => {
  capture([], () =>
    HttpResponse.json(
      { error: { code: 'conflict', message: 'Already reviewed' } },
      { status: 409 },
    ),
  );
  const calls = countRuleGets();
  const { client } = mount();
  const user = await fill('반려');
  const before = calls.get;
  await user.click(submit());
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('충돌: 최신 룰 제안을 다시 불러왔습니다.');
  expect(alert).toHaveTextContent('Already reviewed');
  await waitFor(() => expect(calls.get).toBeGreaterThan(before));
  expect(client.getQueryState(LIST)?.isInvalidated).toBe(true);
  server.events.removeAllListeners();
});

it('separates a saved review from a failed refetch and keeps the form locked', async () => {
  let saved = false;
  capture([], () => {
    saved = true;
    return HttpResponse.json({ ...WEB, status: 'approved', reviewer: 'reviewer-demo' });
  });
  server.use(
    http.get('*/api/rules/:id', () =>
      saved
        ? HttpResponse.json({ error: { code: 'internal', message: 'GET 실패' } }, { status: 500 })
        : undefined,
    ),
  );
  mount();
  const user = await fill('승인');
  await user.click(submit());
  expect(await screen.findByText(/검토가 저장되었습니다/)).toBeInTheDocument();
  expect(
    await screen.findByText('최신 룰 제안을 조회하지 못했습니다. 상세 조회를 다시 시도하세요.'),
  ).toBeInTheDocument();
  expect(submit()).toBeDisabled();
});

it.each([
  ['rp_web_approved', '승인된 룰 제안입니다. 승인은 SIEM 반영을 뜻하지 않습니다.'],
  ['rp_cloud_rejected', '반려된 룰 제안입니다.'],
  ['rp_case_deployed', '서버가 배포됨 상태로 알려 준 룰 제안입니다.'],
])('closes the form for %s and shows the current status', async (id, message) => {
  mount(`/rules/${id}`);
  expect(await screen.findByText(message)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '검토 제출' })).toBeNull();
  expect(screen.queryByLabelText('검토자')).toBeNull();
});

it('does not treat an unknown status as draft', async () => {
  server.use(
    http.get('*/api/rules/:id', () => HttpResponse.json({ ...WEB, status: 'example.paused' })),
  );
  mount();
  expect(
    await screen.findByText('알 수 없는 상태(example.paused)입니다. 검토 폼을 열지 않습니다.'),
  ).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '검토 제출' })).toBeNull();
});
