import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import { routes } from '../app/router';
import { ThemeProvider } from '../lib/theme';
import { server } from '../mocks/server';
import { data } from '../mocks/data';
import untrusted from '../../../tests/fixtures/frontend/untrusted-text.json';

function mount(path = '/tickets', interval = false as number | false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: interval, staleTime: 1000 } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return { ...view, client };
}

it('renders server order, shared lookup cache, safe values and detail links without review controls', async () => {
  let alerts = 0;
  server.use(
    http.get('*/api/tickets', () =>
      HttpResponse.json({ items: [data.tickets[2], data.tickets[0]], next_cursor: null }),
    ),
    http.get('*/api/alerts/:id', () => {
      alerts++;
      return HttpResponse.json(data.alerts[0]);
    }),
  );
  mount();
  const links = await screen.findAllByRole('link', { name: /^tk_/ });
  expect(links.map((link) => link.textContent)).toEqual(['tk_custom', 'tk_sample']);
  expect(links[0]).toHaveAttribute('href', '/tickets/tk_custom');
  expect(await screen.findAllByText('web-01')).toHaveLength(2);
  expect(alerts).toBe(1);
  expect(screen.getByText(/example\.custom/)).toBeInTheDocument();
  expect(screen.getByText(/example\.specialist/)).toBeInTheDocument();
  expect(screen.getAllByText('자산 정보 없음').length).toBeGreaterThan(0);
  expect(screen.getAllByText('없음').length).toBeGreaterThan(0);
  expect(screen.getAllByTitle(String(data.tickets[0].created_at)).length).toBeGreaterThan(0);
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.queryByText('뒤집기')).not.toBeInTheDocument();
});

it('renders attacker and LLM strings as plain text, including nested extensions', async () => {
  const ticket = structuredClone(data.tickets[0]);
  ticket.verdict!.summary = untrusted.summary;
  ticket.extensions = { ...untrusted.extensions, 'example.nested': { value: untrusted.payload } };
  server.use(
    http.get('*/api/tickets', () => HttpResponse.json({ items: [ticket], next_cursor: null })),
  );
  const { container } = mount();
  expect(await screen.findByText(untrusted.summary)).toBeInTheDocument();
  expect(screen.getByText(untrusted.extensions['example.note'])).toBeInTheDocument();
  expect(screen.getByText(/window.compromised/)).toBeInTheDocument();
  expect(container.querySelector('script, img, iframe')).toBeNull();
  expect(container.querySelector('a[href^="https://example.com"]')).toBeNull();
});

it('loads more only on demand and polls every loaded page using fresh cursors without duplicates', async () => {
  let version = 0;
  const cursors: string[] = [];
  server.use(
    http.get('*/api/tickets', ({ request }) => {
      const cursor = new URL(request.url).searchParams.get('cursor') ?? 'first';
      cursors.push(`${version}:${cursor}`);
      if (cursor === 'first')
        return HttpResponse.json({
          items: [data.tickets[version ? 2 : 0]],
          next_cursor: version ? 'fresh' : 'next',
        });
      return HttpResponse.json({ items: [data.tickets[version ? 0 : 1]], next_cursor: null });
    }),
  );
  const { client, unmount } = mount('/tickets', 100);
  await screen.findByRole('link', { name: 'tk_sample' });
  expect(cursors.some((cursor) => cursor.endsWith(':next'))).toBe(false);
  await userEvent.click(screen.getByRole('button', { name: '더 보기' }));
  await screen.findByRole('link', { name: 'tk_cloud' });
  version = 1;
  await waitFor(() =>
    expect(screen.queryByRole('link', { name: 'tk_cloud' })).not.toBeInTheDocument(),
  );
  expect(screen.getAllByRole('link', { name: /^tk_/ }).map((link) => link.textContent)).toEqual([
    'tk_custom',
    'tk_sample',
  ]);
  expect(cursors).toContain('1:fresh');
  expect(cursors).not.toContain('1:next');
  unmount();
  client.clear();
});

it('distinguishes list loading, errors, retry and empty results', async () => {
  server.use(
    http.get('*/api/tickets', () =>
      HttpResponse.json({ error: { code: 'internal', message: '목록 실패' } }, { status: 500 }),
    ),
  );
  mount();
  expect(screen.getByText('티켓 불러오는 중…')).toBeInTheDocument();
  const error = await screen.findByRole('alert');
  expect(error).toHaveTextContent('목록 실패');
  server.use(http.get('*/api/tickets', () => HttpResponse.json({ items: [], next_cursor: null })));
  await userEvent.click(within(error).getByRole('button', { name: '다시 시도' }));
  expect(await screen.findByText('티켓이 없습니다.')).toBeInTheDocument();
});

it('retries failed lookup without presenting it as a null asset', async () => {
  server.use(
    http.get('*/api/tickets', () =>
      HttpResponse.json({ items: [data.tickets[0]], next_cursor: null }),
    ),
    http.get('*/api/alerts/:id', () =>
      HttpResponse.json({ error: { code: 'internal', message: '알럿 실패' } }, { status: 500 }),
    ),
  );
  mount();
  const error = await screen.findByRole('alert');
  expect(error).toHaveTextContent('알럿 실패');
  expect(screen.queryByText('자산 정보 없음')).not.toBeInTheDocument();
  server.use(http.get('*/api/alerts/:id', () => HttpResponse.json(data.alerts[0])));
  await userEvent.click(within(error).getByRole('button', { name: '다시 시도' }));
  expect(await screen.findByText('web-01')).toBeInTheDocument();
});

it('shows all statuses and nullable verdicts, multiple alerts, shared assets and privileged accounts', async () => {
  const user = userEvent.setup();
  mount();
  expect(await screen.findByRole('link', { name: 'tk_tie_a' })).toBeInTheDocument();
  expect(await screen.findAllByText('공용 자산')).toHaveLength(2);
  expect(screen.getAllByText('관리자 계정')).toHaveLength(2);
  expect(screen.getAllByText('신규')).toHaveLength(3);
  await user.click(screen.getByRole('button', { name: 'tk_tie_a 복사' }));
  expect(await navigator.clipboard.readText()).toBe('tk_tie_a');
  await user.click(screen.getByRole('button', { name: '다크 모드' }));
  expect(document.documentElement).toHaveClass('dark');
  await user.click(screen.getByRole('button', { name: '라이트 모드' }));
  expect(document.documentElement).not.toHaveClass('dark');
  await user.click(screen.getByRole('link', { name: 'tk_tie_a' }));
  expect(screen.getByRole('main')).toBeEmptyDOMElement();
});

it('keeps loaded rows when the next page fails and retries the same cursor', async () => {
  let failed = true;
  server.use(
    http.get('*/api/tickets', ({ request }) => {
      if (!new URL(request.url).searchParams.has('cursor'))
        return HttpResponse.json({ items: [data.tickets[0]], next_cursor: 'next' });
      if (failed)
        return HttpResponse.json(
          { error: { code: 'internal', message: '다음 페이지 실패' } },
          { status: 500 },
        );
      return HttpResponse.json({ items: [data.tickets[1]], next_cursor: null });
    }),
  );
  mount();
  await screen.findByRole('link', { name: 'tk_sample' });
  await userEvent.click(screen.getByRole('button', { name: '더 보기' }));
  const error = await screen.findByRole('alert');
  expect(screen.getByRole('link', { name: 'tk_sample' })).toBeInTheDocument();
  failed = false;
  await userEvent.click(within(error).getByRole('button', { name: '다시 시도' }));
  expect(await screen.findByRole('link', { name: 'tk_cloud' })).toBeInTheDocument();
  expect(screen.getAllByRole('link', { name: /^tk_/ })).toHaveLength(2);
});
