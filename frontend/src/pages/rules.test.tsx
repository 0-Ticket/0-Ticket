import { createTestQueryClient } from '../test/query-clients';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { afterEach, expect, it } from 'vitest';
import { routes } from '../app/router';
import { ThemeProvider } from '../lib/theme';
import { server } from '../mocks/server';
import fixture from '../../../tests/fixtures/frontend/hunt-rule-detail.json';

// Request listeners are per test; remove them even when a test fails early.
afterEach(() => {
  server.events.removeAllListeners();
});

const [WEB, CLOUD, APPROVED, REJECTED, DEPLOYED] = fixture.rules;

function mount() {
  const client = createTestQueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: ['/rules'] });
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}
const rows = () => screen.getAllByTestId('rule-row');

it('keeps the API order and shows status, syntax, basis links, backtest and reviewer', async () => {
  server.use(
    http.get('*/api/rules', () =>
      HttpResponse.json({ items: [DEPLOYED, CLOUD, WEB, APPROVED, REJECTED], next_cursor: null }),
    ),
  );
  const { container } = mount();
  await screen.findByRole('heading', { name: '룰 제안' });
  await screen.findAllByTestId('rule-row');
  expect(rows().map((row) => row.querySelector('a')?.textContent)).toEqual([
    'rp_case_deployed',
    'rp_cloud_login',
    'rp_web_shell',
    'rp_web_approved',
    'rp_cloud_rejected',
  ]);
  const deployed = within(rows()[0]);
  expect(deployed.getByText('배포됨')).toBeInTheDocument();
  expect(deployed.getByRole('link', { name: 'cs_web_breach' })).toHaveAttribute(
    'href',
    '/cases/cs_web_breach',
  );
  expect(deployed.getByText('헌팅: 없음')).toBeInTheDocument();
  const cloud = within(rows()[1]);
  expect(cloud.getByText('초안')).toBeInTheDocument();
  expect(cloud.getByText('문법 검사 실패')).toBeInTheDocument();
  expect(cloud.getByText('백테스트: 없음')).toBeInTheDocument();
  expect(cloud.getByText('검토자: 없음')).toBeInTheDocument();
  expect(cloud.getByText('사람 확인 필요')).toBeInTheDocument();
  expect(cloud.getByRole('link', { name: 'ht_cloud_login' })).toHaveAttribute(
    'href',
    '/hunts/ht_cloud_login',
  );
  const web = within(rows()[2]);
  expect(web.getByText(WEB.title)).toBeInTheDocument();
  expect(web.getByText('문법 검사 통과')).toBeInTheDocument();
  // Backtest counts are shown as received, never turned into rates or scores.
  expect(web.getByText('백테스트: 공격 구간 3건 · 정상 구간 1건')).toBeInTheDocument();
  expect(web.getByText('Case: 없음')).toBeInTheDocument();
  expect(within(rows()[3]).getByText('승인됨')).toBeInTheDocument();
  expect(within(rows()[3]).getByText(`검토자: ${APPROVED.reviewer}`)).toBeInTheDocument();
  expect(within(rows()[4]).getByText('반려됨')).toBeInTheDocument();
  const created = web.getByText(new Date(WEB.created_at).toLocaleString());
  expect(created).toHaveAttribute('title', String(WEB.created_at));
  expect(container.querySelector('script, img, b, i, a[href^="https:"]')).toBeNull();
});

it('does not look up hunt, case or incident details from the list', async () => {
  const paths: string[] = [];
  server.events.on('request:start', ({ request }) => {
    paths.push(new URL(request.url).pathname);
  });
  mount();
  await screen.findAllByTestId('rule-row');
  expect(paths.filter((path) => /\/api\/(hunts|cases|incidents)\//.test(path))).toEqual([]);
});

it('shows an unknown status as the original string', async () => {
  server.use(
    http.get('*/api/rules', () =>
      HttpResponse.json({ items: [{ ...WEB, status: 'example.paused' }], next_cursor: null }),
    ),
  );
  mount();
  expect(await screen.findByText('example.paused')).toBeInTheDocument();
});

it('loads the next page by cursor and retries a failed list request', async () => {
  let fail = true;
  server.use(
    http.get('*/api/rules', ({ request }) => {
      const cursor = new URL(request.url).searchParams.get('cursor');
      if (!cursor) return HttpResponse.json({ items: [WEB], next_cursor: 'next' });
      if (fail)
        return HttpResponse.json(
          { error: { code: 'internal', message: '목록 실패' } },
          { status: 500 },
        );
      return HttpResponse.json({ items: [CLOUD], next_cursor: null });
    }),
  );
  const user = userEvent.setup();
  mount();
  await user.click(await screen.findByRole('button', { name: '더 보기' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('목록 실패');
  fail = false;
  await user.click(screen.getByRole('button', { name: '다시 시도' }));
  await screen.findByRole('link', { name: 'rp_cloud_login' });
  expect(rows()).toHaveLength(2);
});

it('shows an empty list', async () => {
  server.use(http.get('*/api/rules', () => HttpResponse.json({ items: [], next_cursor: null })));
  mount();
  expect(await screen.findByText('룰 제안이 없습니다.')).toBeInTheDocument();
});
