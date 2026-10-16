import { createTestQueryClient } from '../test/query-clients';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import { routes } from '../app/router';
import { ThemeProvider } from '../lib/theme';
import { server } from '../mocks/server';
import { data } from '../mocks/data';

function mount(path = '/cases') {
  const client = createTestQueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

it('keeps the API order and shows status, Incident link, owners, task counts and local times', async () => {
  const details: string[] = [];
  server.events.on('request:start', ({ request }) => {
    if (/\/api\/incidents\/[^/]+$/.test(new URL(request.url).pathname)) details.push(request.url);
  });
  const { container } = mount();
  const links = await screen.findAllByRole('link', { name: /^cs_/ });
  expect(links.map((link) => link.textContent)).toEqual(data.cases.map((item) => item.case_id));
  expect(links[1]).toHaveAttribute('href', '/cases/cs_web_breach');
  const web = within(links[1].closest('article')!);
  expect(web.getByText('대응 중')).toBeInTheDocument();
  expect(web.getByText(data.cases[1].title)).toBeInTheDocument();
  expect(web.getByRole('link', { name: 'in_escalated' })).toHaveAttribute(
    'href',
    '/incidents/in_escalated',
  );
  expect(web.getByText('담당: analyst-kim, <i>analyst-lee</i>')).toBeInTheDocument();
  expect(web.getByText('작업 3건')).toBeInTheDocument();
  expect(web.getByText('할 일 1 · 진행 중 1 · 완료 1')).toBeInTheDocument();
  expect(web.getByText('종결: 없음')).toBeInTheDocument();
  const sample = within(links[0].closest('article')!);
  expect(sample.getByText('열림')).toBeInTheDocument();
  expect(sample.getByText('할 일 1 · 진행 중 0 · 완료 0')).toBeInTheDocument();
  for (const time of container.querySelectorAll('time'))
    expect(time).toHaveTextContent(new Date(Number(time.title)).toLocaleString());
  expect(container.querySelector('script, img, iframe, b, i, a[href^="https:"]')).toBeNull();
  // The list never loads Incident detail per row.
  expect(details).toEqual([]);
  server.events.removeAllListeners();
});

it('shows an unknown Case status as the original string', async () => {
  server.use(
    http.get('*/api/cases', () =>
      HttpResponse.json({
        items: [{ ...data.cases[0], status: 'example.paused', tasks: [] }],
        next_cursor: null,
      }),
    ),
  );
  mount();
  expect(await screen.findByText('example.paused')).toBeInTheDocument();
  expect(screen.getByText('작업 0건')).toBeInTheDocument();
  expect(screen.getByText('담당: 없음')).toBeInTheDocument();
});

it('loads the next page by cursor and retries a failed list request', async () => {
  let fail = true;
  const cursors: (string | null)[] = [];
  server.use(
    http.get('*/api/cases', ({ request }) => {
      const cursor = new URL(request.url).searchParams.get('cursor');
      cursors.push(cursor);
      if (fail)
        return HttpResponse.json(
          { error: { code: 'internal', message: '목록 실패' } },
          { status: 500 },
        );
      return HttpResponse.json(
        cursor
          ? { items: [data.cases[1]], next_cursor: null }
          : { items: [data.cases[0]], next_cursor: '1' },
      );
    }),
  );
  mount();
  const user = userEvent.setup();
  await screen.findByText('목록 실패');
  fail = false;
  await user.click(screen.getByRole('button', { name: '다시 시도' }));
  await screen.findByRole('link', { name: 'cs_sample' });
  await user.click(screen.getByRole('button', { name: '더 보기' }));
  await screen.findByRole('link', { name: 'cs_web_breach' });
  await waitFor(() => expect(cursors.at(-1)).toBe('1'));
  expect(screen.queryByRole('button', { name: '더 보기' })).not.toBeInTheDocument();
});

it('shows an empty list', async () => {
  server.use(http.get('*/api/cases', () => HttpResponse.json({ items: [], next_cursor: null })));
  mount();
  expect(await screen.findByText('Case가 없습니다.')).toBeInTheDocument();
});
