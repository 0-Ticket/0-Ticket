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

function mount(path = '/incidents') {
  const client = createTestQueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return { ...view, router };
}

it('keeps the API order and shows status, severity, grouping origin, nulls and local times', async () => {
  const { container } = mount();
  const links = await screen.findAllByRole('link', { name: /^in_/ });
  expect(links.map((link) => link.textContent)).toEqual(
    data.incidents.map((item) => item.incident_id),
  );
  expect(links[1]).toHaveAttribute('href', '/incidents/in_web_campaign');
  const web = within(links[1].closest('article')!);
  expect(web.getByText('조사 중')).toBeInTheDocument();
  expect(web.getByText('High')).toBeInTheDocument();
  expect(web.getByText('규칙 묶음')).toBeInTheDocument();
  expect(web.getByText('묶음 항목 3건 · 제외 1건')).toBeInTheDocument();
  expect(web.getByText(data.incidents[1].title)).toBeInTheDocument();
  expect(web.getByText('전술: TA0001, TA0003')).toBeInTheDocument();
  const manual = within(links[2].closest('article')!);
  expect(manual.getByText('사람이 직접 묶음')).toBeInTheDocument();
  expect(manual.getByText('전술: 없음')).toBeInTheDocument();
  expect(manual.getByText('요약: 없음')).toBeInTheDocument();
  expect(within(links[3].closest('article')!).getByText('정상 종결')).toBeInTheDocument();
  for (const time of container.querySelectorAll('time'))
    expect(time).toHaveTextContent(new Date(Number(time.title)).toLocaleString());
  expect(container.querySelector('script, img, b, a[href^="https:"]')).toBeNull();
});

it('loads the next page by cursor and retries a failed list request', async () => {
  let fail = true;
  const cursors: (string | null)[] = [];
  server.use(
    http.get('*/api/incidents', ({ request }) => {
      const cursor = new URL(request.url).searchParams.get('cursor');
      cursors.push(cursor);
      if (fail)
        return HttpResponse.json(
          { error: { code: 'internal', message: '목록 실패' } },
          { status: 500 },
        );
      return HttpResponse.json(
        cursor
          ? { items: [data.incidents[1]], next_cursor: null }
          : { items: [data.incidents[0]], next_cursor: '1' },
      );
    }),
  );
  mount();
  const user = userEvent.setup();
  await screen.findByText('목록 실패');
  fail = false;
  await user.click(screen.getByRole('button', { name: '다시 시도' }));
  await screen.findByRole('link', { name: 'in_sample' });
  await user.click(screen.getByRole('button', { name: '더 보기' }));
  await screen.findByRole('link', { name: 'in_web_campaign' });
  await waitFor(() => expect(cursors.at(-1)).toBe('1'));
  expect(screen.queryByRole('button', { name: '더 보기' })).not.toBeInTheDocument();
});

it('shows an empty list', async () => {
  server.use(
    http.get('*/api/incidents', () => HttpResponse.json({ items: [], next_cursor: null })),
  );
  mount();
  expect(await screen.findByText('Incident가 없습니다.')).toBeInTheDocument();
});
