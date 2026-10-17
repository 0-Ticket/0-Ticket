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

const [WEB, CLOUD] = fixture.rules;

function mount(path: string) {
  const client = createTestQueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return {
    ...render(
      <QueryClientProvider client={client}>
        <ThemeProvider>
          <RouterProvider router={router} />
        </ThemeProvider>
      </QueryClientProvider>,
    ),
    router,
  };
}
const heading = (id: string) => screen.findByRole('heading', { name: `룰 제안 ${id}` });
const region = (name: string) => within(screen.getByRole('region', { name }));

it('shows the rule, query, backtest and basis as plain monospace text', async () => {
  const { container } = mount('/rules/rp_web_shell');
  await heading('rp_web_shell');
  expect(screen.getByRole('navigation', { name: '위치' })).toHaveTextContent('룰 제안 목록');
  expect(screen.getByText(WEB.title)).toBeInTheDocument();
  expect(screen.getByText('초안')).toBeInTheDocument();
  expect(screen.getByText('문법 검사 통과')).toBeInTheDocument();
  expect(screen.getByText('검토자: 없음')).toBeInTheDocument();
  expect(screen.getByText('T1505.003')).toBeInTheDocument();
  expect(screen.getAllByRole('link', { name: 'ht_web' })[0]).toHaveAttribute(
    'href',
    '/hunts/ht_web',
  );
  expect(screen.getByText('근거 Case: 없음')).toBeInTheDocument();
  const sigma = screen.getByRole('region', { name: 'Sigma 룰' }).querySelector('pre');
  expect(sigma).toHaveTextContent(WEB.sigma_rule, { normalizeWhitespace: false });
  const query = region('SIEM 쿼리').getByText(WEB.siem_query!);
  expect(query.tagName).toBe('PRE');
  const backtest = region('백테스트');
  expect(backtest.getByText('3')).toBeInTheDocument();
  expect(backtest.getByText('1')).toBeInTheDocument();
  const start = backtest.getByText(new Date(WEB.backtest!.window_start_at).toLocaleString());
  expect(start).toHaveAttribute('title', String(WEB.backtest!.window_start_at));
  const created = screen.getByText(new Date(WEB.created_at).toLocaleString());
  expect(created).toHaveAttribute('title', String(WEB.created_at));
  expect(container.querySelector('script, img, b, i, a[href^="https:"]')).toBeNull();
  // Approval and deployment are separate: the screen never offers to run or deploy a rule.
  expect(
    screen.queryByRole('button', { name: /배포|활성|비활성|실행|SIEM|백테스트|Deploy|Enable/ }),
  ).toBeNull();
});

it('shows syntax failure, null query, null backtest and the human reason as received', async () => {
  mount('/rules/rp_cloud_login');
  await heading('rp_cloud_login');
  expect(screen.getByText('문법 검사 실패')).toBeInTheDocument();
  expect(region('SIEM 쿼리').getByText('없음')).toBeInTheDocument();
  expect(region('백테스트').getByText('없음')).toBeInTheDocument();
  expect(screen.getByText(CLOUD.human_reason!)).toBeInTheDocument();
});

it('links the Incident recorded on the basis hunt, read from the hunt detail', async () => {
  const user = userEvent.setup();
  const { router } = mount('/rules/rp_web_shell');
  await heading('rp_web_shell');
  const related = within(await screen.findByRole('region', { name: '관련 Incident' }));
  await user.click(await related.findByRole('link', { name: 'in_web_campaign' }));
  expect(router.state.location.pathname).toBe('/incidents/in_web_campaign');
});

it('shows "없음" when the basis hunt has no Incident', async () => {
  mount('/rules/rp_cloud_login');
  await heading('rp_cloud_login');
  const related = within(screen.getByRole('region', { name: '관련 Incident' }));
  expect(await related.findByText('Incident: 없음')).toBeInTheDocument();
});

it('links the Incident of the basis Case when only case_id is present', async () => {
  const paths: string[] = [];
  server.events.on('request:start', ({ request }) => {
    paths.push(new URL(request.url).pathname);
  });
  mount('/rules/rp_case_deployed');
  await heading('rp_case_deployed');
  expect(screen.getByText('배포됨')).toBeInTheDocument();
  expect(screen.getAllByRole('link', { name: 'cs_web_breach' })[0]).toHaveAttribute(
    'href',
    '/cases/cs_web_breach',
  );
  const related = within(screen.getByRole('region', { name: '관련 Incident' }));
  expect(await related.findByRole('link', { name: 'in_escalated' })).toHaveAttribute(
    'href',
    '/incidents/in_escalated',
  );
  expect(paths.some((path) => path.endsWith('/cases/cs_web_breach'))).toBe(true);
  expect(paths.some((path) => /\/api\/hunts\//.test(path))).toBe(false);
  server.events.removeAllListeners();
});

it('keeps a basis lookup failure inside the related Incident area and retries only it', async () => {
  let fail = true;
  const calls = { rule: 0, hunt: 0 };
  server.events.on('request:start', ({ request }) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith('/rules/rp_web_shell')) calls.rule += 1;
    if (path.endsWith('/hunts/ht_web')) calls.hunt += 1;
  });
  server.use(
    http.get('*/api/hunts/:id', () =>
      fail
        ? HttpResponse.json({ error: { code: 'internal', message: '헌팅 실패' } }, { status: 500 })
        : undefined,
    ),
  );
  const user = userEvent.setup();
  mount('/rules/rp_web_shell');
  await heading('rp_web_shell');
  const related = within(screen.getByRole('region', { name: '관련 Incident' }));
  expect(await related.findByRole('alert')).toHaveTextContent('헌팅 실패');
  expect(screen.getByRole('region', { name: 'Sigma 룰' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '검토 제출' })).toBeInTheDocument();
  fail = false;
  const before = calls.rule;
  await user.click(related.getByRole('button', { name: '다시 시도' }));
  await related.findByRole('link', { name: 'in_web_campaign' });
  expect(calls.rule).toBe(before);
  expect(calls.hunt).toBeGreaterThanOrEqual(2);
  server.events.removeAllListeners();
});

it('shows a rule lookup failure', async () => {
  mount('/rules/rp_missing');
  expect(await screen.findByRole('alert')).toHaveTextContent('Object not found');
  expect(screen.queryByRole('region', { name: '관련 Incident' })).not.toBeInTheDocument();
});
