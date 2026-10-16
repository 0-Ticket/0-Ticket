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
import fixture from '../../../tests/fixtures/frontend/case-detail.json';

const CASE = fixture.cases[0];
const ARTIFACT = fixture.artifacts[0];

function mount(path = '/cases/cs_web_breach') {
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
const heading = (id: string) => screen.findByRole('heading', { name: `Case ${id}` });
const region = (name: string) => within(screen.getByRole('region', { name }));

it('shows the Case, its Incident link, lessons, extensions and rule proposals as text', async () => {
  const { container } = mount();
  await heading('cs_web_breach');
  expect(screen.getByRole('navigation', { name: '위치' })).toHaveTextContent('Case 목록');
  expect(screen.getByText('대응 중')).toBeInTheDocument();
  expect(screen.getByText(CASE.title)).toBeInTheDocument();
  expect(screen.getByText('종결: 없음')).toBeInTheDocument();
  const created = screen.getByText(new Date(CASE.created_at).toLocaleString());
  expect(created).toHaveAttribute('title', String(CASE.created_at));
  const incident = screen.getAllByRole('link', { name: 'in_escalated' });
  expect(incident[0]).toHaveAttribute('href', '/incidents/in_escalated');
  // Lessons are written on close; an open Case shows null as "없음".
  expect(region('교훈').getByText('없음')).toBeInTheDocument();
  expect(screen.getByText(CASE.extensions['example.external_case']!)).toBeInTheDocument();
  expect(screen.getByText('{"hours":4}')).toBeInTheDocument();
  expect(region('룰 제안').getByRole('link', { name: 'rp_case_web' })).toHaveAttribute(
    'href',
    '/rules/rp_case_web',
  );
  await screen.findByRole('region', { name: '보고서' });
  expect(container.querySelector('script, img, iframe, b, i, a[href^="https:"]')).toBeNull();
});

it('shows the related Incident report: timeline, evidence, IOCs and recommendations', async () => {
  const user = userEvent.setup();
  const { router } = mount();
  await heading('cs_web_breach');
  const report = within(await screen.findByRole('region', { name: '보고서' }));
  expect(report.getByText(ARTIFACT.timeline[0].description)).toBeInTheDocument();
  expect(report.getByText(ARTIFACT.suspected_cause)).toBeInTheDocument();
  expect(report.getByRole('link', { name: 'tk_tie_z' })).toHaveAttribute(
    'href',
    '/tickets/tk_tie_z',
  );
  // Registered values the screen does not know stay as their original strings.
  expect(report.getByText('example.case_note')).toBeInTheDocument();
  expect(report.queryByRole('link', { name: 'note_case_1' })).not.toBeInTheDocument();
  expect(report.getByText('example.ja3')).toBeInTheDocument();
  expect(report.getByText('https://example.com/case.php?id=<script>')).toBeInTheDocument();
  expect(report.getByText('권고 · 실행하지 않음')).toBeInTheDocument();
  expect(report.getByText(ARTIFACT.recommendations[0].action)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /격리|실행/ })).not.toBeInTheDocument();
  await user.click(region('관련 Incident').getByRole('link', { name: 'in_escalated' }));
  expect(router.state.location.pathname).toBe('/incidents/in_escalated');
});

it('shows a closed Case with its closed time, lessons as text and a null report as "없음"', async () => {
  const closed = fixture.cases[1];
  const { container } = mount('/cases/cs_contained');
  await heading('cs_contained');
  expect(screen.getByText('종결')).toBeInTheDocument();
  expect(screen.getByText(new Date(closed.closed_at!).toLocaleString())).toHaveAttribute(
    'title',
    String(closed.closed_at),
  );
  expect(region('교훈').getByText(closed.lessons!)).toBeInTheDocument();
  expect(region('룰 제안').getByText('없음')).toBeInTheDocument();
  expect(screen.getByText('확장 필드 (0)')).toBeInTheDocument();
  // in_contained has no C11; the mock answers artifact null.
  const report = within(await screen.findByRole('region', { name: '보고서' }));
  expect(report.getByText('없음')).toBeInTheDocument();
  expect(container.querySelector('script, img, iframe, b, i, a[href^="https:"]')).toBeNull();
});

it('keeps an Incident failure apart from the Case and retries only the Incident', async () => {
  let fail = true;
  const calls = { case: 0, incident: 0 };
  server.events.on('request:start', ({ request }) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith('/cases/cs_web_breach')) calls.case += 1;
    if (path.endsWith('/incidents/in_escalated')) calls.incident += 1;
  });
  server.use(
    http.get('*/api/incidents/:id', () =>
      fail
        ? HttpResponse.json(
            { error: { code: 'internal', message: 'Incident 실패' } },
            { status: 500 },
          )
        : undefined,
    ),
  );
  const user = userEvent.setup();
  mount();
  await heading('cs_web_breach');
  const related = within(await screen.findByRole('region', { name: '관련 Incident' }));
  expect(await related.findByRole('alert')).toHaveTextContent('Incident 실패');
  // The Case itself and its tasks remain visible.
  expect(screen.getByRole('region', { name: '작업' })).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: '보고서' })).not.toBeInTheDocument();
  fail = false;
  const before = calls.case;
  await user.click(related.getByRole('button', { name: '다시 시도' }));
  await screen.findByRole('region', { name: '보고서' });
  expect(calls.case).toBe(before);
  expect(calls.incident).toBeGreaterThanOrEqual(2);
  server.events.removeAllListeners();
});

it('shows a Case lookup failure', async () => {
  mount('/cases/cs_missing');
  expect(await screen.findByRole('alert')).toHaveTextContent('Object not found');
  expect(screen.queryByRole('region', { name: '관련 Incident' })).not.toBeInTheDocument();
});
