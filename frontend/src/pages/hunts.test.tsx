import { createTestQueryClient } from '../test/query-clients';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import { routes } from '../app/router';
import { ThemeProvider } from '../lib/theme';
import { server } from '../mocks/server';
import fixture from '../../../tests/fixtures/frontend/hunt-rule-detail.json';
import incidentFixture from '../../../tests/fixtures/frontend/incident-detail.json';

const CLOUD = fixture.hunts[0];
const QUIET = fixture.hunts[1];
const WEB = incidentFixture.hunts[0];

function mount() {
  const client = createTestQueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: ['/hunts'] });
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}
const rows = () => screen.getAllByTestId('hunt-row');

it('keeps the API order and shows C17 values, Incident links and local times', async () => {
  server.use(
    http.get('*/api/hunts', () =>
      HttpResponse.json({ items: [QUIET, CLOUD, WEB], next_cursor: null }),
    ),
  );
  const { container } = mount();
  await screen.findByRole('heading', { name: '헌팅 결과' });
  await screen.findAllByTestId('hunt-row');
  expect(rows().map((row) => row.querySelector('a')?.textContent)).toEqual([
    'ht_baseline_quiet',
    'ht_cloud_login',
    'ht_web',
  ]);
  const quiet = within(rows()[0]);
  expect(quiet.getByText('이상 없음')).toBeInTheDocument();
  expect(quiet.getByText('통계 기준선')).toBeInTheDocument();
  expect(quiet.getByText('Unknown')).toBeInTheDocument();
  expect(quiet.getByText('Incident: 없음')).toBeInTheDocument();
  expect(quiet.getByText('기법: 없음')).toBeInTheDocument();
  expect(quiet.getByText('근거 0건')).toBeInTheDocument();
  const cloud = within(rows()[1]);
  expect(cloud.getByText('이상 징후')).toBeInTheDocument();
  expect(cloud.getByText('가설 기반')).toBeInTheDocument();
  expect(cloud.getByText('사람 확인 필요')).toBeInTheDocument();
  expect(cloud.getByText(CLOUD.hypothesis)).toBeInTheDocument();
  expect(cloud.getByText('근거 2건')).toBeInTheDocument();
  expect(cloud.getByText('룰 후보: 예')).toBeInTheDocument();
  const created = cloud.getByText(new Date(CLOUD.created_at).toLocaleString());
  expect(created).toHaveAttribute('title', String(CLOUD.created_at));
  expect(within(rows()[2]).getByRole('link', { name: 'in_web_campaign' })).toHaveAttribute(
    'href',
    '/incidents/in_web_campaign',
  );
  expect(rows()[1].querySelector('a')).toHaveAttribute('href', '/hunts/ht_cloud_login');
  // Attacker text stays text: no element or URL link is created from hypothesis strings.
  expect(container.querySelector('script, img, b, i, a[href^="https:"]')).toBeNull();
});

it('shows an unknown method as the original string', async () => {
  server.use(
    http.get('*/api/hunts', () =>
      HttpResponse.json({ items: [{ ...QUIET, method: 'example.ml' }], next_cursor: null }),
    ),
  );
  mount();
  expect(await screen.findByText('example.ml')).toBeInTheDocument();
});

it('loads the next page by cursor and retries a failed list request', async () => {
  let fail = true;
  server.use(
    http.get('*/api/hunts', ({ request }) => {
      const cursor = new URL(request.url).searchParams.get('cursor');
      if (!cursor) return HttpResponse.json({ items: [CLOUD], next_cursor: 'next' });
      if (fail)
        return HttpResponse.json(
          { error: { code: 'internal', message: '목록 실패' } },
          { status: 500 },
        );
      return HttpResponse.json({ items: [QUIET], next_cursor: null });
    }),
  );
  const user = userEvent.setup();
  mount();
  await user.click(await screen.findByRole('button', { name: '더 보기' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('목록 실패');
  fail = false;
  await user.click(screen.getByRole('button', { name: '다시 시도' }));
  await screen.findByRole('link', { name: 'ht_baseline_quiet' });
  expect(rows()).toHaveLength(2);
  expect(screen.queryByRole('button', { name: '더 보기' })).not.toBeInTheDocument();
});

it('shows an empty list', async () => {
  server.use(http.get('*/api/hunts', () => HttpResponse.json({ items: [], next_cursor: null })));
  mount();
  expect(await screen.findByText('헌팅 결과가 없습니다.')).toBeInTheDocument();
});
